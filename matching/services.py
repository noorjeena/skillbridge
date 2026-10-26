from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification, User
from accounts.services import create_notification
from profiles.models import StudentProfile

from .models import Conversation, LearningPartnership, Match, MatchRequest, Message


SKILL_WEIGHT = 60
PROFICIENCY_WEIGHT = 15
AVAILABILITY_WEIGHT = 15
TRUST_WEIGHT = 10

TEACHING_LEVELS = {
    'BEGINNER': 1,
    'INTERMEDIATE': 2,
    'ADVANCED': 3,
    'EXPERT': 4,
}
LEARNING_LEVELS = {
    'BEGINNER': 1,
    'INTERMEDIATE': 2,
    'ADVANCED': 3,
}


@dataclass(frozen=True)
class MatchCalculation:
    student_one: object
    student_two: object
    compatibility_score: int
    match_type: str
    matched_skills: dict
    score_breakdown: dict


def _direction(learner, teacher):
    learning = {
        item.skill_id: item
        for item in learner.learning_skills.filter(skill__is_active=True).select_related('skill')
    }
    offered = {
        item.skill_id: item
        for item in teacher.offered_skills.filter(skill__is_active=True).select_related('skill')
    }
    matches = []
    fit_scores = []

    for skill_id in sorted(learning.keys() & offered.keys()):
        learning_item = learning[skill_id]
        offered_item = offered[skill_id]
        desired_level = LEARNING_LEVELS[learning_item.learning_level]
        teacher_level = TEACHING_LEVELS[offered_item.proficiency]
        fit_scores.append(min(teacher_level / desired_level, 1.0))
        matches.append({
            'skill_id': skill_id,
            'skill': offered_item.skill.name,
            'teacher_level': offered_item.get_proficiency_display(),
            'learning_level': learning_item.get_learning_level_display(),
        })

    return matches, fit_scores


def _optional_component(value, weight, name):
    if value is None:
        return None
    if not 0 <= value <= 1:
        raise ValueError(f'{name} must be between 0 and 1.')
    return round(weight * value, 2)


def calculate_match(student_a, student_b, *, availability_fit=None, trust_fit=None):
    """Return a rule-based match calculation, or None when there is no learning direction.

    Optional availability_fit and trust_fit values are 0..1 fractions. They are
    currently unavailable in the project and are excluded from score normalization.
    """
    if student_a.pk == student_b.pk:
        return None

    if student_a.pk < student_b.pk:
        student_one, student_two = student_a, student_b
        one_learns_from_two, one_fit = _direction(student_one, student_two)
        two_learns_from_one, two_fit = _direction(student_two, student_one)
    else:
        student_one, student_two = student_b, student_a
        one_learns_from_two, one_fit = _direction(student_one, student_two)
        two_learns_from_one, two_fit = _direction(student_two, student_one)

    if not one_learns_from_two and not two_learns_from_one:
        return None

    is_reciprocal = bool(one_learns_from_two and two_learns_from_one)
    match_type = Match.MatchType.DIRECT_EXCHANGE if is_reciprocal else Match.MatchType.ONE_WAY_LEARNING
    skill_points = (SKILL_WEIGHT // 2) * (
        bool(one_learns_from_two) + bool(two_learns_from_one)
    )
    all_fits = one_fit + two_fit
    proficiency_points = round(
        PROFICIENCY_WEIGHT * (sum(all_fits) / len(all_fits)),
        2,
    )

    components = {
        'skill': {'points': skill_points, 'available_weight': SKILL_WEIGHT},
        'proficiency': {'points': proficiency_points, 'available_weight': PROFICIENCY_WEIGHT},
        'availability': {
            'points': _optional_component(availability_fit, AVAILABILITY_WEIGHT, 'availability_fit'),
            'available_weight': AVAILABILITY_WEIGHT if availability_fit is not None else 0,
        },
        'trust': {
            'points': _optional_component(trust_fit, TRUST_WEIGHT, 'trust_fit'),
            'available_weight': TRUST_WEIGHT if trust_fit is not None else 0,
        },
    }
    weighted_points = sum(component['points'] or 0 for component in components.values())
    available_weight = sum(component['available_weight'] for component in components.values())
    score = round(weighted_points * 100 / available_weight)

    return MatchCalculation(
        student_one=student_one,
        student_two=student_two,
        compatibility_score=max(0, min(100, score)),
        match_type=match_type,
        matched_skills={
            'student_one_learns_from_two': one_learns_from_two,
            'student_two_learns_from_one': two_learns_from_one,
        },
        score_breakdown=components,
    )


def get_or_create_match(student_a, student_b):
    calculation = calculate_match(student_a, student_b)
    if calculation is None:
        return None

    match, created = Match.objects.get_or_create(
        student_one=calculation.student_one,
        student_two=calculation.student_two,
        defaults={
            'compatibility_score': calculation.compatibility_score,
            'match_type': calculation.match_type,
            'matched_skills': calculation.matched_skills,
            'score_breakdown': calculation.score_breakdown,
        },
    )
    if not created:
        Match.objects.filter(pk=match.pk).update(
            compatibility_score=calculation.compatibility_score,
            match_type=calculation.match_type,
            matched_skills=calculation.matched_skills,
            score_breakdown=calculation.score_breakdown,
            updated_at=timezone.now(),
        )
        match.refresh_from_db()
    return match


def discover_matches(student):
    candidates = (
        StudentProfile.objects.filter(user__role=User.Role.STUDENT, user__is_active=True)
        .exclude(pk=student.pk)
        .select_related('user')
        .prefetch_related('offered_skills__skill', 'learning_skills__skill')
        .order_by('pk')
    )
    matches = []
    for candidate in candidates:
        match = get_or_create_match(student, candidate)
        if match is not None and match.status != Match.Status.ACCEPTED:
            matches.append(match)
    return sorted(matches, key=lambda match: match.compatibility_score, reverse=True)


def send_match_request(match, sender, message=''):
    try:
        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=match.pk)
            if sender.pk == match.student_one_id:
                receiver = match.student_two
            elif sender.pk == match.student_two_id:
                receiver = match.student_one
            else:
                raise ValidationError('You are not a participant in this match.')

            if calculate_match(match.student_one, match.student_two) is None:
                raise ValidationError('This pair no longer has a compatible learning direction.')
            if match.status == Match.Status.ACCEPTED:
                raise ValidationError('This match already has an active partnership.')
            if match.requests.filter(status=MatchRequest.Status.PENDING).exists():
                raise ValidationError('There is already an active request for this match.')

            match_request = MatchRequest.objects.create(
                match=match,
                sender=sender,
                receiver=receiver,
                message=message,
            )
            match.status = Match.Status.REQUESTED
            match.save(update_fields=('status', 'updated_at'))

            create_notification(
                receiver.user,
                Notification.NotificationType.MATCH_REQUEST,
                'New match request',
                f'{sender.user.username} wants to connect as a learning partner.',
                reverse('matching:requests'),
            )
            return match_request
    except IntegrityError as error:
        raise ValidationError('There is already an active request for this match.') from error


def respond_to_match_request(match_request, respondent, *, accept):
    with transaction.atomic():
        match_request = (
            MatchRequest.objects.select_for_update()
            .select_related('match', 'match__student_one', 'match__student_two', 'sender__user', 'receiver__user')
            .get(pk=match_request.pk)
        )
        if match_request.receiver_id != respondent.pk:
            raise PermissionError('Only the request receiver can respond.')
        if match_request.status != MatchRequest.Status.PENDING:
            raise ValidationError('This request has already been answered.')

        now = timezone.now()
        match = match_request.match
        if accept:
            match_request.status = MatchRequest.Status.ACCEPTED
            match.status = Match.Status.ACCEPTED
            one_learns_from_two = match.matched_skills['student_one_learns_from_two']
            two_learns_from_one = match.matched_skills['student_two_learns_from_one']
            primary_teacher = None
            primary_learner = None
            if match.match_type == Match.MatchType.ONE_WAY_LEARNING:
                if one_learns_from_two:
                    primary_teacher, primary_learner = match.student_two, match.student_one
                else:
                    primary_teacher, primary_learner = match.student_one, match.student_two

            partnership, _ = LearningPartnership.objects.get_or_create(
                match=match,
                defaults={
                    'student_one': match.student_one,
                    'student_two': match.student_two,
                    'relationship_type': match.match_type,
                    'primary_teacher': primary_teacher,
                    'primary_learner': primary_learner,
                },
            )
            from learning.services import create_directions_for_partnership

            create_directions_for_partnership(partnership)
            get_or_create_conversation(partnership)
            create_notification(
                match_request.sender.user,
                Notification.NotificationType.MATCH_ACCEPTED,
                'Match accepted',
                f'{respondent.user.username} accepted your learning match request.',
                reverse('matching:partnerships'),
            )
        else:
            match_request.status = MatchRequest.Status.REJECTED
            match.status = Match.Status.REJECTED
            partnership = None
            create_notification(
                match_request.sender.user,
                Notification.NotificationType.MATCH_REJECTED,
                'Match request declined',
                f'{respondent.user.username} declined your learning match request.',
                reverse('matching:requests'),
            )

        match_request.responded_at = now
        match_request.save(update_fields=('status', 'responded_at'))
        match.save(update_fields=('status', 'updated_at'))
        return partnership


def get_or_create_conversation(partnership):
    if partnership is None:
        raise ValueError('A partnership is required to create a conversation.')
    if partnership.status != LearningPartnership.Status.ACTIVE:
        raise ValidationError('Only active partnerships can have conversations.')
    conversation, _ = Conversation.objects.get_or_create(partnership=partnership)
    return conversation


def conversation_for_user(user, conversation_id):
    profile = user.student_profile
    return (
        Conversation.objects.filter(
            pk=conversation_id,
            partnership__status=LearningPartnership.Status.ACTIVE,
        )
        .filter(
            Q(partnership__student_one=profile) | Q(partnership__student_two=profile)
        )
        .select_related(
            'partnership__student_one__user',
            'partnership__student_two__user',
        )
        .first()
    )


def mark_conversation_read(conversation, user):
    Message.objects.filter(conversation=conversation, is_read=False).exclude(sender=user).update(is_read=True)


def unread_count_for_user(user):
    profile = user.student_profile
    return Message.objects.filter(
        Q(conversation__partnership__student_one=profile) | Q(conversation__partnership__student_two=profile),
        is_read=False,
    ).exclude(sender=user).count()


def send_message(conversation, sender, content):
    if sender.role != 'STUDENT':
        raise PermissionError('Only students can send messages.')
    profile = sender.student_profile
    if conversation.partnership.student_one_id != profile.pk and conversation.partnership.student_two_id != profile.pk:
        raise PermissionError('You are not a participant in this conversation.')

    cleaned = (content or '').strip()
    if not cleaned:
        raise ValidationError('Message content is required.')
    if len(cleaned) > 2000:
        raise ValidationError('Messages must be 2000 characters or fewer.')

    message = Message.objects.create(
        conversation=conversation,
        sender=sender,
        content=cleaned,
        is_read=False,
    )
    recipient = conversation.other_student_for(profile).user
    create_notification(
        recipient,
        Notification.NotificationType.NEW_MESSAGE,
        'New message',
        f'{sender.username} sent you a message in your skill partnership chat.',
        reverse('chat:chat-detail', args=(conversation.pk,)),
    )
    return message