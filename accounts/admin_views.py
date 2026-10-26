from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from learning.models import (
    Assignment,
    Evaluation,
    LearningDirection,
    LearningSession,
    Review,
    Submission,
)
from matching.models import Conversation, LearningPartnership, Match, MatchRequest, Message
from skills.models import LearningSkill, OfferedSkill, Skill

from .admin_forms import AdminSkillForm
from .models import Notification, User


class AdminRequiredMixin(LoginRequiredMixin):
    login_url = 'admin-login'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role != User.Role.ADMIN:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def profile_name(profile):
    if profile is None:
        return '—'
    return profile.full_name or profile.user.username


def status_badge(value, label=None):
    normalized = str(value).lower()
    styles = {
        'active': 'is-success',
        'accepted': 'is-success',
        'completed': 'is-success',
        'evaluated': 'is-success',
        'read': 'is-success',
        'pending': 'is-warning',
        'requested': 'is-warning',
        'scheduled': 'is-info',
        'submitted': 'is-info',
        'draft': 'is-muted',
        'suggested': 'is-muted',
        'inactive': 'is-muted',
        'cancelled': 'is-muted',
        'rejected': 'is-danger',
        'closed': 'is-muted',
        'unread': 'is-warning',
    }
    return {'text': label or str(value).title(), 'badge': styles.get(normalized, 'is-muted')}


class AdminDashboardHomeView(AdminRequiredMixin, TemplateView):
    template_name = 'admin_dashboard/overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        directions = LearningDirection.objects.all()
        submissions = Submission.objects.all()
        conversations = Conversation.objects.all()
        context.update({
            'page_title': 'Overview',
            'now': timezone.now(),
            'student_count': User.objects.filter(role=User.Role.STUDENT).count(),
            'active_student_count': User.objects.filter(
                role=User.Role.STUDENT,
                is_active=True,
            ).count(),
            'skill_count': Skill.objects.count(),
            'active_skill_count': Skill.objects.filter(is_active=True).count(),
            'inactive_skill_count': Skill.objects.filter(is_active=False).count(),
            'pending_request_count': MatchRequest.objects.filter(status=MatchRequest.Status.PENDING).count(),
            'accepted_partnership_count': LearningPartnership.objects.filter(
                status=LearningPartnership.Status.ACTIVE,
            ).count(),
            'active_direction_count': directions.filter(status=LearningDirection.Status.ACTIVE).count(),
            'scheduled_session_count': LearningSession.objects.filter(
                status=LearningSession.Status.SCHEDULED,
            ).count(),
            'completed_session_count': LearningSession.objects.filter(
                status=LearningSession.Status.COMPLETED,
            ).count(),
            'pending_submission_count': submissions.filter(
                status=Submission.Status.SUBMITTED,
            ).exclude(
                evaluation__status=Evaluation.Status.EVALUATED,
            ).count(),
            'evaluated_submission_count': submissions.filter(status=Submission.Status.EVALUATED).count(),
            'review_count': Review.objects.count(),
            'conversation_count': conversations.count(),
            'message_count': Message.objects.count(),
            'unread_notification_count': Notification.objects.filter(is_read=False).count(),
            'recent_requests': MatchRequest.objects.select_related(
                'sender__user', 'receiver__user',
            ).order_by('-created_at')[:6],
            'recent_sessions': LearningSession.objects.select_related(
                'learning_direction__teacher__user',
                'learning_direction__learner__user',
                'learning_direction__skill',
            ).order_by('-created_at')[:6],
        })
        return context


class AdminTableView(AdminRequiredMixin, TemplateView):
    template_name = 'admin_dashboard/list.html'
    page_size = 20
    page_title = ''
    page_description = ''
    table_columns = ()
    filter_options = ()
    search_placeholder = 'Search'
    create_url_name = None
    create_label = None

    def get_items(self):
        return []

    def make_rows(self, items):
        return items

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = Paginator(self.get_items(), self.page_size)
        page_obj = paginator.get_page(self.request.GET.get('page'))
        context.update({
            'page_title': self.page_title,
            'page_description': self.page_description,
            'columns': self.table_columns,
            'rows': self.make_rows(page_obj.object_list),
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': page_obj.has_other_pages(),
            'filter_options': self.filter_options,
            'search_placeholder': self.search_placeholder,
            'current_search': self.request.GET.get('q', ''),
            'current_filter': self.request.GET.get('filter', ''),
            'create_url': reverse(self.create_url_name) if self.create_url_name else None,
            'create_label': self.create_label,
        })
        return context


class AdminSkillListView(AdminTableView):
    page_title = 'Skill catalogue'
    page_description = 'Manage the active catalogue students use to build teaching and learning profiles.'
    table_columns = ('Skill', 'Category', 'Status', 'Teaching', 'Learning', 'Created', 'Actions')
    search_placeholder = 'Search skills'
    filter_options = (
        ('', 'All skills'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        *((f'category:{value}', label) for value, label in Skill.Category.choices),
    )
    create_url_name = 'admin_dashboard:skill-add'
    create_label = 'Add skill'

    def get_items(self):
        queryset = Skill.objects.annotate(
            teaching_count=Count('offerings__profile', distinct=True),
            learning_count=Count('learners__profile', distinct=True),
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        current_filter = self.request.GET.get('filter', '')
        if current_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif current_filter == 'inactive':
            queryset = queryset.filter(is_active=False)
        elif current_filter.startswith('category:'):
            queryset = queryset.filter(category=current_filter.split(':', 1)[1])
        return queryset.order_by('name')

    def make_rows(self, items):
        rows = []
        for skill in items:
            rows.append({
                'cells': (
                    {'text': skill.name, 'strong': True, 'secondary': skill.description},
                    skill.get_category_display(),
                    status_badge('Active' if skill.is_active else 'Inactive'),
                    skill.teaching_count,
                    skill.learning_count,
                    skill.created_at.strftime('%b %d, %Y') if skill.created_at else '—',
                ),
                'edit_url': reverse('admin_dashboard:skill-edit', args=(skill.pk,)),
                'toggle_url': reverse('admin_dashboard:skill-toggle', args=(skill.pk,)),
                'delete_url': reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
                'toggle_label': 'Deactivate' if skill.is_active else 'Activate',
                'is_active': skill.is_active,
            })
        return rows


class AdminUserListView(AdminTableView):
    page_title = 'Users'
    page_description = 'Review student accounts and profile readiness.'
    table_columns = ('Student', 'Email', 'Department', 'Year', 'Profile', 'Status', 'Joined')
    search_placeholder = 'Search students'
    filter_options = (('', 'All students'), ('active', 'Active'), ('inactive', 'Inactive'))

    def get_items(self):
        queryset = User.objects.filter(role=User.Role.STUDENT).select_related('student_profile').annotate(
            offered_count=Count('student_profile__offered_skills', distinct=True),
            learning_count=Count('student_profile__learning_skills', distinct=True),
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(student_profile__full_name__icontains=search)
                | Q(student_profile__department__icontains=search)
            )
        account_filter = self.request.GET.get('filter', '')
        if account_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif account_filter == 'inactive':
            queryset = queryset.filter(is_active=False)
        return queryset.order_by('-date_joined')

    def make_rows(self, items):
        rows = []
        for user in items:
            profile = getattr(user, 'student_profile', None)
            completion = profile.completion_percentage if profile else 0
            rows.append({
                'cells': (
                    {'text': profile_name(profile), 'strong': True, 'secondary': user.username},
                    user.email or '—',
                    profile.department if profile and profile.department else '—',
                    profile.academic_year if profile and profile.academic_year else '—',
                    f'{completion}% · {user.offered_count} teach / {user.learning_count} learn',
                    status_badge('Active' if user.is_active else 'Inactive'),
                    user.date_joined.strftime('%b %d, %Y'),
                ),
                'detail_url': reverse('admin_dashboard:user-detail', args=(user.pk,)),
            })
        return rows


class AdminUserDetailView(AdminRequiredMixin, TemplateView):
    template_name = 'admin_dashboard/user_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(
            User.objects.filter(role=User.Role.STUDENT).select_related('student_profile'),
            pk=self.kwargs['pk'],
        )
        profile = getattr(user, 'student_profile', None)
        context.update({
            'page_title': 'Student profile',
            'student': user,
            'profile': profile,
            'offered_skills': OfferedSkill.objects.filter(profile=profile).select_related('skill') if profile else [],
            'learning_skills': LearningSkill.objects.filter(profile=profile).select_related('skill') if profile else [],
            'partnership_count': LearningPartnership.objects.filter(
                Q(student_one=profile) | Q(student_two=profile),
            ).count() if profile else 0,
            'direction_count': LearningDirection.objects.filter(
                Q(teacher=profile) | Q(learner=profile),
            ).count() if profile else 0,
            'session_count': LearningSession.objects.filter(
                Q(learning_direction__teacher=profile) | Q(learning_direction__learner=profile),
            ).count() if profile else 0,
            'review_count': Review.objects.filter(
                Q(reviewer=profile) | Q(reviewee=profile),
            ).count() if profile else 0,
        })
        return context


class AdminMatchListView(AdminTableView):
    page_title = 'Matches & requests'
    page_description = 'Monitor match types and request outcomes without changing student decisions.'
    table_columns = ('Students', 'Type', 'Score', 'Request status', 'Created')
    search_placeholder = 'Search students'
    filter_options = (
        ('', 'All requests'),
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('type:DIRECT_EXCHANGE', 'Direct exchange'),
        ('type:ONE_WAY_LEARNING', 'One-way learning'),
    )

    def get_items(self):
        queryset = MatchRequest.objects.select_related(
            'sender__user', 'receiver__user', 'match',
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(sender__full_name__icontains=search)
                | Q(sender__user__username__icontains=search)
                | Q(receiver__full_name__icontains=search)
                | Q(receiver__user__username__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter.startswith('type:'):
            queryset = queryset.filter(match__match_type=current_filter.split(':', 1)[1])
        elif current_filter:
            queryset = queryset.filter(status=current_filter.upper())
        return queryset.order_by('-created_at')

    def make_rows(self, items):
        return [{
            'cells': (
                {'text': f'{profile_name(item.sender)} → {profile_name(item.receiver)}', 'strong': True},
                item.match.get_match_type_display(),
                f'{item.match.compatibility_score}%',
                status_badge(item.status, item.get_status_display()),
                item.created_at.strftime('%b %d, %Y'),
            ),
        } for item in items]


class AdminPartnershipListView(AdminTableView):
    page_title = 'Partnerships'
    page_description = 'Read-only overview of student partnerships, directions, plans, and progress.'
    table_columns = ('Students', 'Type', 'Directions', 'Plans', 'Lesson progress', 'Status', 'Created')
    search_placeholder = 'Search students'
    filter_options = (('', 'All partnerships'), ('active', 'Active'), ('cancelled', 'Cancelled'))

    def get_items(self):
        queryset = LearningPartnership.objects.select_related(
            'student_one__user', 'student_two__user',
        ).prefetch_related(
            'learning_directions__skill',
            'learning_directions__learning_plans__lessons',
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(student_one__full_name__icontains=search)
                | Q(student_one__user__username__icontains=search)
                | Q(student_two__full_name__icontains=search)
                | Q(student_two__user__username__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter:
            queryset = queryset.filter(status=current_filter.upper())
        return queryset.order_by('-created_at')

    def make_rows(self, items):
        rows = []
        for partnership in items:
            directions = list(partnership.learning_directions.all())
            plan_count = sum(direction.learning_plans.count() for direction in directions)
            lessons = [
                lesson
                for direction in directions
                for plan in direction.learning_plans.all()
                for lesson in plan.lessons.all()
            ]
            completed = sum(lesson.status == 'COMPLETED' for lesson in lessons)
            progress = f'{completed}/{len(lessons)} lessons' if lessons else 'No lessons'
            direction_skills = ', '.join(direction.skill.name for direction in directions) or '—'
            rows.append({
                'cells': (
                    {'text': f'{profile_name(partnership.student_one)} & {profile_name(partnership.student_two)}', 'strong': True},
                    f'{partnership.get_relationship_type_display()} · {direction_skills}',
                    len(directions),
                    plan_count,
                    progress,
                    status_badge(partnership.status, partnership.get_status_display()),
                    partnership.created_at.strftime('%b %d, %Y'),
                ),
            })
        return rows


class AdminSessionListView(AdminTableView):
    page_title = 'Learning sessions'
    page_description = 'Monitor scheduled, completed, and cancelled sessions. Meeting links are not shown.'
    table_columns = ('Session', 'Teacher', 'Learner', 'Skill / lesson', 'Scheduled', 'Status')
    search_placeholder = 'Search sessions or students'
    filter_options = (
        ('', 'All sessions'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    def get_items(self):
        queryset = LearningSession.objects.select_related(
            'learning_direction__teacher__user',
            'learning_direction__learner__user',
            'learning_direction__skill',
            'lesson',
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(learning_direction__teacher__full_name__icontains=search)
                | Q(learning_direction__teacher__user__username__icontains=search)
                | Q(learning_direction__learner__full_name__icontains=search)
                | Q(learning_direction__learner__user__username__icontains=search)
                | Q(learning_direction__skill__name__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter:
            queryset = queryset.filter(status=current_filter.upper())
        return queryset.order_by('-scheduled_start')

    def make_rows(self, items):
        return [{
            'cells': (
                {'text': item.title, 'strong': True},
                profile_name(item.learning_direction.teacher),
                profile_name(item.learning_direction.learner),
                f'{item.learning_direction.skill.name} · {item.lesson.title}' if item.lesson else item.learning_direction.skill.name,
                timezone.localtime(item.scheduled_start).strftime('%b %d, %Y · %I:%M %p'),
                status_badge(item.status, item.get_status_display()),
            ),
        } for item in items]


class AdminAssignmentListView(AdminTableView):
    page_title = 'Assignments'
    page_description = 'Monitor assignment availability, learner submissions, and teacher evaluation status.'
    table_columns = ('Assignment', 'Skill', 'Teacher', 'Learner', 'Submission', 'Evaluation', 'Due')
    search_placeholder = 'Search assignments or students'
    filter_options = (
        ('', 'All activity'),
        ('status:ACTIVE', 'Active'),
        ('status:CLOSED', 'Closed'),
        ('submission:SUBMITTED', 'Submitted'),
        ('submission:EVALUATED', 'Evaluated'),
        ('evaluation:PENDING', 'Pending evaluation'),
    )

    def get_items(self):
        latest_submission = Submission.objects.select_related('learner__user', 'evaluation')
        queryset = Assignment.objects.select_related(
            'lesson__learning_plan__learning_direction__skill',
            'lesson__learning_plan__learning_direction__teacher__user',
            'lesson__learning_plan__learning_direction__learner__user',
        ).prefetch_related(
            Prefetch('submissions', queryset=latest_submission, to_attr='admin_submissions'),
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(lesson__learning_plan__learning_direction__teacher__user__username__icontains=search)
                | Q(lesson__learning_plan__learning_direction__learner__user__username__icontains=search)
                | Q(lesson__learning_plan__learning_direction__skill__name__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter.startswith('status:'):
            queryset = queryset.filter(status=current_filter.split(':', 1)[1])
        elif current_filter.startswith('submission:'):
            queryset = queryset.filter(submissions__status=current_filter.split(':', 1)[1]).distinct()
        elif current_filter == 'evaluation:PENDING':
            queryset = queryset.filter(
                submissions__status=Submission.Status.SUBMITTED,
            ).filter(
                Q(submissions__evaluation__isnull=True)
                | Q(submissions__evaluation__status=Evaluation.Status.PENDING),
            ).distinct()
        return queryset.order_by('-created_at')

    def make_rows(self, items):
        rows = []
        for assignment in items:
            submissions = assignment.admin_submissions or [None]
            direction = assignment.lesson.learning_plan.learning_direction
            for submission in submissions:
                evaluation = getattr(submission, 'evaluation', None) if submission else None
                evaluation_label = (
                    evaluation.get_status_display()
                    if evaluation
                    else ('Pending' if submission and submission.status == Submission.Status.SUBMITTED else '—')
                )
                rows.append({
                    'cells': (
                        {'text': assignment.title, 'strong': True, 'secondary': assignment.get_status_display()},
                        direction.skill.name,
                        profile_name(direction.teacher),
                        profile_name(submission.learner) if submission else profile_name(direction.learner),
                        status_badge(submission.status, submission.get_status_display()) if submission else status_badge('No submission'),
                        status_badge(evaluation_label),
                        assignment.due_date.strftime('%b %d, %Y') if assignment.due_date else '—',
                    ),
                })
        return rows


class AdminReviewListView(AdminTableView):
    page_title = 'Reviews & trust'
    page_description = 'Read-only review monitoring; existing learner eligibility and review rules remain enforced.'
    table_columns = ('Reviewer', 'Reviewee', 'Skill', 'Rating', 'Comment', 'Created')
    search_placeholder = 'Search reviews'
    filter_options = (
        ('', 'All ratings'),
        ('rating:5', '5 stars'),
        ('rating:4', '4 stars'),
        ('rating:3', '3 stars'),
        ('rating:2', '2 stars'),
        ('rating:1', '1 star'),
    )

    def get_items(self):
        queryset = Review.objects.select_related(
            'reviewer__user', 'reviewee__user', 'learning_direction__skill',
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(reviewer__full_name__icontains=search)
                | Q(reviewer__user__username__icontains=search)
                | Q(reviewee__full_name__icontains=search)
                | Q(reviewee__user__username__icontains=search)
                | Q(learning_direction__skill__name__icontains=search)
                | Q(comment__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter.startswith('rating:'):
            queryset = queryset.filter(rating=current_filter.split(':', 1)[1])
        return queryset.order_by('-created_at')

    def make_rows(self, items):
        return [{
            'cells': (
                profile_name(item.reviewer),
                profile_name(item.reviewee),
                item.learning_direction.skill.name,
                {'text': f'{item.rating} / 5', 'strong': True},
                item.comment or 'No written comment',
                item.created_at.strftime('%b %d, %Y'),
            ),
        } for item in items]


class AdminMessageListView(AdminTableView):
    page_title = 'Messages'
    page_description = 'Conversation activity only. Private message content is intentionally not displayed here.'
    table_columns = ('Participants', 'Partnership', 'Messages', 'Latest message', 'Conversation created')
    search_placeholder = 'Search participants'

    def get_items(self):
        queryset = Conversation.objects.select_related(
            'partnership__student_one__user',
            'partnership__student_two__user',
            'partnership__match',
        ).annotate(
            message_count=Count('messages'),
            latest_message_at=Max('messages__created_at'),
        )
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(partnership__student_one__full_name__icontains=search)
                | Q(partnership__student_one__user__username__icontains=search)
                | Q(partnership__student_two__full_name__icontains=search)
                | Q(partnership__student_two__user__username__icontains=search)
            )
        return queryset.order_by('-latest_message_at', '-created_at')

    def make_rows(self, items):
        return [{
            'cells': (
                {'text': f'{profile_name(item.partnership.student_one)} & {profile_name(item.partnership.student_two)}', 'strong': True},
                item.partnership.get_relationship_type_display(),
                item.message_count,
                timezone.localtime(item.latest_message_at).strftime('%b %d, %Y · %I:%M %p') if item.latest_message_at else 'No messages',
                item.created_at.strftime('%b %d, %Y'),
            ),
        } for item in items]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['message_count'] = Message.objects.count()
        return context


class AdminNotificationListView(AdminTableView):
    page_title = 'Notifications'
    page_description = 'Monitor delivery volume and read state. Related URLs are not exposed in this dashboard.'
    table_columns = ('Recipient', 'Type', 'Notification', 'Status', 'Created')
    search_placeholder = 'Search notification or recipient'
    filter_options = (
        ('', 'All notifications'),
        ('unread', 'Unread'),
        ('read', 'Read'),
        *((f'type:{value}', label) for value, label in Notification.NotificationType.choices),
    )

    def get_items(self):
        queryset = Notification.objects.select_related('recipient')
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(message__icontains=search)
                | Q(recipient__username__icontains=search)
                | Q(recipient__email__icontains=search)
            )
        current_filter = self.request.GET.get('filter', '')
        if current_filter in ('read', 'unread'):
            queryset = queryset.filter(is_read=current_filter == 'read')
        elif current_filter.startswith('type:'):
            queryset = queryset.filter(notification_type=current_filter.split(':', 1)[1])
        return queryset.order_by('-created_at')

    def make_rows(self, items):
        return [{
            'cells': (
                item.recipient.username,
                item.get_notification_type_display(),
                {'text': item.title, 'strong': True, 'secondary': item.message},
                status_badge('Read' if item.is_read else 'Unread'),
                item.created_at.strftime('%b %d, %Y · %I:%M %p'),
            ),
        } for item in items]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'notification_total': Notification.objects.count(),
            'notification_unread': Notification.objects.filter(is_read=False).count(),
            'notification_read': Notification.objects.filter(is_read=True).count(),
        })
        return context


class AdminSkillCreateView(AdminRequiredMixin, CreateView):
    form_class = AdminSkillForm
    template_name = 'admin_dashboard/skill_form.html'
    success_url = reverse_lazy('admin_dashboard:skills')
    extra_context = {'page_title': 'Add skill', 'submit_label': 'Create skill'}

    def form_valid(self, form):
        messages.success(self.request, 'Skill added to the catalogue.')
        return super().form_valid(form)


class AdminSkillUpdateView(AdminRequiredMixin, UpdateView):
    model = Skill
    form_class = AdminSkillForm
    template_name = 'admin_dashboard/skill_form.html'
    success_url = reverse_lazy('admin_dashboard:skills')
    extra_context = {'page_title': 'Edit skill', 'submit_label': 'Save changes'}

    def form_valid(self, form):
        messages.success(self.request, 'Skill catalogue entry updated.')
        return super().form_valid(form)


def skill_reference_count(skill):
    count = (
        skill.offerings.count()
        + skill.learners.count()
        + skill.learning_directions.count()
    )
    if count:
        return count

    for matched_skills in Match.objects.values_list('matched_skills', flat=True).iterator():
        if not isinstance(matched_skills, dict):
            return 1
        for directions in matched_skills.values():
            if not isinstance(directions, list):
                return 1
            for item in directions:
                if not isinstance(item, dict):
                    return 1
                if item.get('skill_id') == skill.pk:
                    count += 1
                    break
            if count:
                return count
    return count


class AdminSkillToggleView(AdminRequiredMixin, View):
    def get(self, request, pk):
        skill = get_object_or_404(Skill, pk=pk)
        return self.render_confirmation(request, skill)

    def post(self, request, pk):
        skill = get_object_or_404(Skill, pk=pk)
        skill.is_active = not skill.is_active
        skill.save(update_fields=('is_active',))
        message = 'Skill deactivated and removed from new student selections.' if not skill.is_active else 'Skill activated and available for student selection.'
        messages.success(request, message)
        return redirect('admin_dashboard:skills')

    def render_confirmation(self, request, skill):
        from django.shortcuts import render

        return render(request, 'admin_dashboard/skill_toggle_confirm.html', {
            'page_title': 'Deactivate skill' if skill.is_active else 'Activate skill',
            'skill': skill,
            'will_activate': not skill.is_active,
        })


class AdminSkillDeleteView(AdminRequiredMixin, View):
    def get(self, request, pk):
        skill = get_object_or_404(Skill, pk=pk)
        reference_count = skill_reference_count(skill)
        return self.render_confirmation(request, skill, reference_count)

    def post(self, request, pk):
        skill = get_object_or_404(Skill, pk=pk)
        reference_count = skill_reference_count(skill)
        if reference_count:
            messages.error(
                request,
                'This skill is referenced by student or historical learning records. It was not deleted; deactivate it instead.',
            )
            return redirect('admin_dashboard:skill-delete', pk=skill.pk)
        try:
            skill.delete()
        except ProtectedError:
            messages.error(
                request,
                'This skill has protected student or learning records. It was not deleted; deactivate it instead.',
            )
            return redirect('admin_dashboard:skill-delete', pk=skill.pk)
        messages.success(request, 'Unused skill permanently deleted.')
        return redirect('admin_dashboard:skills')

    def render_confirmation(self, request, skill, reference_count):
        from django.shortcuts import render

        return render(request, 'admin_dashboard/skill_delete_confirm.html', {
            'page_title': 'Delete skill',
            'skill': skill,
            'reference_count': reference_count,
            'deactivate_url': reverse('admin_dashboard:skill-toggle', args=(skill.pk,)),
        })
