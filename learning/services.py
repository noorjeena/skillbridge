from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.services import create_notification

from .models import Assignment, Evaluation, LearningDirection, LearningSession, Review, Submission
from profiles.models import StudentProfile


@transaction.atomic
def create_directions_for_partnership(partnership):
    if partnership.status != partnership.Status.ACTIVE:
        raise ValidationError('Learning directions require an active partnership.')

    directions = []
    matched_skills = partnership.match.matched_skills
    direction_specs = (
        (
            partnership.student_two,
            partnership.student_one,
            matched_skills.get('student_one_learns_from_two', []),
        ),
        (
            partnership.student_one,
            partnership.student_two,
            matched_skills.get('student_two_learns_from_one', []),
        ),
    )

    for teacher, learner, skill_items in direction_specs:
        for item in skill_items:
            direction, created = LearningDirection.objects.get_or_create(
                partnership=partnership,
                teacher=teacher,
                learner=learner,
                skill_id=item['skill_id'],
                defaults={'status': LearningDirection.Status.ACTIVE},
            )
            if created:
                direction.full_clean()
                direction.save()
            directions.append(direction)

    if not directions:
        raise ValidationError('The accepted match has no learning directions.')
    return directions


@transaction.atomic
def save_evaluation(submission_id, evaluator, *, score=None, feedback=''):
    submission = (
        Submission.objects.select_for_update()
        .select_related('assignment__lesson__learning_plan__learning_direction__teacher__user', 'learner__user')
        .get(pk=submission_id)
    )
    direction = submission.assignment.lesson.learning_plan.learning_direction
    if direction.teacher.user_id != evaluator.pk:
        raise PermissionDenied('Only the direction teacher can evaluate this submission.')
    if submission.status not in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED):
        raise ValidationError('Only submitted work can be evaluated.')
    if submission.submitted_at is None:
        raise ValidationError('A submission must be submitted before it can be evaluated.')
    if score is None and not (feedback or '').strip():
        raise ValidationError('Provide feedback or a score to complete the evaluation.')

    evaluation, created = Evaluation.objects.get_or_create(
        submission=submission,
        defaults={
            'evaluator': evaluator,
            'feedback': feedback,
            'score': score,
            'status': Evaluation.Status.EVALUATED,
        },
    )
    should_notify = created or evaluation.status != Evaluation.Status.EVALUATED
    evaluation.evaluator = evaluator
    evaluation.feedback = feedback
    evaluation.score = score
    evaluation.status = Evaluation.Status.EVALUATED
    evaluation.full_clean()
    evaluation.save()

    submission.status = Submission.Status.EVALUATED
    submission.updated_at = timezone.now()
    submission.save(update_fields=('status', 'updated_at'))

    if should_notify:
        create_notification(
            submission.learner.user,
            Notification.NotificationType.ASSIGNMENT_EVALUATED,
            'Assignment evaluated',
            f'{evaluator.username} evaluated your submission for {submission.assignment.title}.',
            reverse('learning:submission-detail', args=(submission.pk,)),
        )
    return evaluation


def notify_assignment_created(assignment):
    if assignment.status != Assignment.Status.ACTIVE:
        return None
    direction = assignment.lesson.learning_plan.learning_direction
    return create_notification(
        direction.learner.user,
        Notification.NotificationType.ASSIGNMENT_CREATED,
        'New assignment',
        f'{assignment.created_by.username} added {assignment.title} to your {direction.skill.name} learning plan.',
        reverse('learning:assignment-detail', args=(assignment.pk,)),
    )


def notify_assignment_submitted(submission):
    direction = submission.assignment.lesson.learning_plan.learning_direction
    return create_notification(
        direction.teacher.user,
        Notification.NotificationType.ASSIGNMENT_SUBMITTED,
        'Assignment submitted',
        f'{submission.learner.full_name or submission.learner.user.username} submitted {submission.assignment.title}.',
        reverse('learning:submission-detail', args=(submission.pk,)),
    )


def create_review(learning_direction_id, reviewer_user, *, rating, comment=''):
    direction = None
    reviewer_profile = None
    try:
        with transaction.atomic():
            direction = LearningDirection.objects.select_for_update().select_related(
                'teacher__user', 'learner__user', 'skill',
            ).get(pk=learning_direction_id)
            reviewer_profile = StudentProfile.objects.filter(user=reviewer_user).first()
            if reviewer_profile is None or direction.learner_id != reviewer_profile.pk:
                raise PermissionDenied('Only the learning direction learner can review this teacher.')
            if not direction.sessions.filter(status=LearningSession.Status.COMPLETED).exists():
                raise ValidationError('A review is available only after a completed learning session.')
            if Review.objects.filter(learning_direction=direction, reviewer=reviewer_profile).exists():
                raise ValidationError('You have already reviewed this learning direction.')

            review = Review(
                learning_direction=direction,
                reviewer=reviewer_profile,
                reviewee=direction.teacher,
                rating=rating,
                comment=comment,
            )
            review.full_clean()
            review.save()
            create_notification(
                direction.teacher.user,
                Notification.NotificationType.REVIEW_RECEIVED,
                'New learning review',
                f'{reviewer_profile.full_name or reviewer_user.username} reviewed your {direction.skill.name} teaching.',
                reverse('profile-detail'),
            )
            return review
    except IntegrityError as error:
        if (
            direction is not None
            and reviewer_profile is not None
            and Review.objects.filter(
                learning_direction=direction,
                reviewer=reviewer_profile,
            ).exists()
        ):
            raise ValidationError('You have already reviewed this learning direction.') from error
        raise


@transaction.atomic
def update_review(review_id, reviewer_user, *, rating, comment=''):
    review = Review.objects.select_for_update().select_related(
        'reviewer__user', 'reviewee__user', 'learning_direction__skill',
    ).get(pk=review_id)
    if review.reviewer.user_id != reviewer_user.pk:
        raise PermissionDenied('Only the reviewer can edit this review.')
    review.rating = rating
    review.comment = comment
    review.full_clean()
    review.save(update_fields=('rating', 'comment', 'updated_at'))
    return review


@transaction.atomic
def notify_session_event(session, *, status_change, actor, message=None):
    if session.learning_direction_id is None:
        return None
    recipient = session.learning_direction.learner.user
    if actor.pk == recipient.pk:
        recipient = session.learning_direction.teacher.user
    title = {
        LearningSession.Status.SCHEDULED: 'Session scheduled',
        LearningSession.Status.CANCELLED: 'Session cancelled',
        LearningSession.Status.COMPLETED: 'Session completed',
    }.get(status_change, 'Session updated')
    notification_type = {
        LearningSession.Status.SCHEDULED: Notification.NotificationType.SESSION_SCHEDULED,
        LearningSession.Status.CANCELLED: Notification.NotificationType.SESSION_CANCELLED,
        LearningSession.Status.COMPLETED: Notification.NotificationType.SESSION_COMPLETED,
    }.get(status_change, Notification.NotificationType.SESSION_UPDATED)
    create_notification(
        recipient,
        notification_type,
        title,
        message or f'{actor.username} updated the session: {session.title}.',
        reverse('learning:session-detail', args=(session.pk,)),
    )
    return recipient
