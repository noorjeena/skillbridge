from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from accounts.models import User
from profiles.models import StudentProfile

from .forms import MatchRequestForm
from .models import Conversation, LearningPartnership, Match, MatchRequest
from .services import (
    discover_matches,
    mark_conversation_read,
    respond_to_match_request,
    send_match_request,
)


class StudentRequiredMixin(LoginRequiredMixin):
	def dispatch(self, request, *args, **kwargs):
		if not request.user.is_authenticated:
			return self.handle_no_permission()
		if request.user.role != User.Role.STUDENT:
			raise PermissionDenied
		return super().dispatch(request, *args, **kwargs)


class MatchContextMixin:
	def get_pair_context(self, match):
		current_profile_id = self.request.user.student_profile.pk
		if match.student_one_id == current_profile_id:
			partner = match.student_two
			you_learn = match.matched_skills['student_one_learns_from_two']
			partner_learns = match.matched_skills['student_two_learns_from_one']
		else:
			partner = match.student_one
			you_learn = match.matched_skills['student_two_learns_from_one']
			partner_learns = match.matched_skills['student_one_learns_from_two']
		return {
			'match': match,
			'partner': partner,
			'you_learn': you_learn,
			'partner_learns': partner_learns,
		}


class MatchDiscoveryView(StudentRequiredMixin, TemplateView):
	template_name = 'matching/match_list.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		student = get_object_or_404(StudentProfile, user=self.request.user)
		recommendations = []
		for match in discover_matches(student):
			pair_context = MatchContextMixin.get_pair_context(self, match)
			active_request = match.requests.filter(status=MatchRequest.Status.PENDING).first()
			recommendations.append({
				**pair_context,
				'active_request': active_request,
				'can_request': active_request is None,
			})

		context['recommendations'] = sorted(
			recommendations,
			key=lambda item: item['match'].compatibility_score,
			reverse=True,
		)
		return context


class MatchDetailView(StudentRequiredMixin, MatchContextMixin, DetailView):
	model = Match
	template_name = 'matching/match_detail.html'
	context_object_name = 'match'

	def get_queryset(self):
		return Match.objects.filter(
			Q(student_one__user=self.request.user) | Q(student_two__user=self.request.user),
		).select_related('student_one__user', 'student_two__user')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(self.get_pair_context(self.object))
		context['pending_request'] = self.object.requests.filter(status=MatchRequest.Status.PENDING).first()
		context['request_form'] = MatchRequestForm()
		partner = context['partner']
		context['partner_rating_average'] = partner.average_rating
		context['partner_review_count'] = partner.review_count
		context['partner_reviews'] = partner.received_reviews.select_related(
			'reviewer__user',
			'learning_direction__skill',
		)
		return context


class MatchRequestsView(StudentRequiredMixin, TemplateView):
	template_name = 'matching/requests.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		context['received_requests'] = MatchRequest.objects.filter(
			receiver=profile,
			status=MatchRequest.Status.PENDING,
		).select_related('sender__user', 'match')
		context['sent_requests'] = MatchRequest.objects.filter(
			sender=profile,
			status=MatchRequest.Status.PENDING,
		).select_related('receiver__user', 'match')
		return context


class MatchRequestCreateView(StudentRequiredMixin, FormView):
	form_class = MatchRequestForm

	def form_valid(self, form):
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		match = get_object_or_404(
			Match.objects.filter(
				Q(student_one=profile) | Q(student_two=profile),
			),
			pk=self.kwargs['pk'],
		)
		try:
			send_match_request(match, profile, form.cleaned_data['message'])
		except ValidationError as error:
			messages.error(self.request, error.messages[0])
			return redirect('matching:detail', pk=match.pk)

		messages.success(self.request, 'Your learning request has been sent.')
		return redirect('matching:requests')

	def form_invalid(self, form):
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		match = get_object_or_404(
			Match.objects.filter(Q(student_one=profile) | Q(student_two=profile)),
			pk=self.kwargs['pk'],
		)
		messages.error(self.request, 'Please shorten your note and try again.')
		return redirect('matching:detail', pk=match.pk)


class MatchRequestRespondView(StudentRequiredMixin, View):
	def post(self, request, pk, action):
		profile = get_object_or_404(StudentProfile, user=request.user)
		match_request = get_object_or_404(MatchRequest, pk=pk, receiver=profile)
		try:
			partnership = respond_to_match_request(
				match_request,
				profile,
				accept=action == 'accept',
			)
		except ValidationError as error:
			messages.error(request, error.messages[0])
		else:
			if partnership:
				messages.success(request, 'Request accepted. Your learning partnership is active.')
			else:
				messages.info(request, 'Request rejected.')
		return redirect('matching:requests')


class LearningPartnershipListView(StudentRequiredMixin, ListView):
	template_name = 'matching/partnerships.html'
	context_object_name = 'partnerships'

	def get_queryset(self):
		from learning.models import Review

		profile = self.request.user.student_profile
		return LearningPartnership.objects.filter(
			Q(student_one__user=self.request.user) | Q(student_two__user=self.request.user),
			status=LearningPartnership.Status.ACTIVE,
		).select_related(
			'student_one__user', 'student_two__user', 'primary_teacher__user', 'primary_learner__user',
		).prefetch_related(
			'learning_directions__teacher__user',
			'learning_directions__learner__user',
			'learning_directions__skill',
			'learning_directions__learning_plans__lessons__assignments__submissions',
			'learning_directions__sessions',
			Prefetch(
				'learning_directions__reviews',
				queryset=Review.objects.filter(reviewer=profile),
				to_attr='viewer_reviews',
			),
		)

	def get_context_data(self, **kwargs):
		from learning.models import LearningSession

		context = super().get_context_data(**kwargs)
		profile = self.request.user.student_profile
		for partnership in context['partnerships']:
			for direction in partnership.learning_directions.all():
				direction.viewer_review = direction.viewer_reviews[0] if direction.viewer_reviews else None
				direction.can_review = (
					direction.learner_id == profile.pk
					and any(
						session.status == LearningSession.Status.COMPLETED
						for session in direction.sessions.all()
					)
				)
		return context


class ChatListView(StudentRequiredMixin, TemplateView):
	template_name = 'matching/chat_list.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		conversations = (
			Conversation.objects.filter(
				partnership__status=LearningPartnership.Status.ACTIVE,
			)
			.filter(Q(partnership__student_one=profile) | Q(partnership__student_two=profile))
			.select_related('partnership__student_one__user', 'partnership__student_two__user')
			.order_by('-created_at')
		)
		items = []
		for conversation in conversations:
			other_student = conversation.other_student_for(profile)
			last_message = conversation.messages.order_by('-created_at').first()
			items.append({
				'pk': conversation.pk,
				'other_user': other_student.user,
				'last_message': last_message,
				'unread_count': conversation.messages.filter(is_read=False).exclude(sender=self.request.user).count(),
				'partnership': conversation.partnership,
			})
		context['conversations'] = items
		return context


class ChatConversationDetailView(StudentRequiredMixin, DetailView):
	model = Conversation
	pk_url_kwarg = 'conversation_id'
	template_name = 'matching/chat_detail.html'
	context_object_name = 'conversation'

	def get_queryset(self):
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		return Conversation.objects.filter(
			partnership__status=LearningPartnership.Status.ACTIVE,
		).filter(Q(partnership__student_one=profile) | Q(partnership__student_two=profile)).select_related(
			'partnership__student_one__user',
			'partnership__student_two__user',
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = self.request.user.student_profile
		context['other_student'] = self.object.other_student_for(profile)
		context['messages'] = self.object.messages.select_related('sender__student_profile').order_by('created_at')
		mark_conversation_read(self.object, self.request.user)
		return context
