from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView
from urllib.parse import urlsplit

from .models import Notification, User
from .services import get_unread_count, get_notifications, mark_all_as_read, mark_as_read
from .forms import LoginForm, RegistrationForm


class HomeView(TemplateView):
	template_name = 'accounts/home.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		if self.request.user.is_authenticated and self.request.user.role == 'STUDENT':
			from matching.models import LearningPartnership, MatchRequest
			from matching.services import discover_matches
			from learning.models import LearningSession

			profile = self.request.user.student_profile
			context['matching_dashboard'] = {
				'recommended': len(discover_matches(profile)),
				'requests_sent': MatchRequest.objects.filter(
					sender=profile,
					status=MatchRequest.Status.PENDING,
				).count(),
				'requests_received': MatchRequest.objects.filter(
					receiver=profile,
					status=MatchRequest.Status.PENDING,
				).count(),
				'partnerships': LearningPartnership.objects.filter(
					Q(student_one=profile) | Q(student_two=profile),
					status=LearningPartnership.Status.ACTIVE,
				).count(),
			}
			context['upcoming_sessions'] = LearningSession.objects.filter(
				Q(learning_direction__teacher=profile) | Q(learning_direction__learner=profile),
				status=LearningSession.Status.SCHEDULED,
				scheduled_end__gte=timezone.now(),
			).select_related('learning_direction__skill')[:5]
		return context


class RegisterView(CreateView):
	form_class = RegistrationForm
	template_name = 'accounts/register.html'
	success_url = reverse_lazy('login')


class LoginView(auth_views.LoginView):
	authentication_form = LoginForm
	template_name = 'accounts/login.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['admin_login'] = self.request.resolver_match.url_name == 'admin-login'
		return context

	def get_success_url(self):
		if self.request.user.role == User.Role.ADMIN:
			return reverse('admin_dashboard:overview')

		redirect_url = self.get_redirect_url()
		if redirect_url and urlsplit(redirect_url).path.startswith(
			reverse('admin_dashboard:overview')
		):
			return reverse('home')
		return super().get_success_url()


class LogoutView(auth_views.LogoutView):
	pass


class StudentNotificationMixin(LoginRequiredMixin):
	def dispatch(self, request, *args, **kwargs):
		if not request.user.is_authenticated:
			return self.handle_no_permission()
		if request.user.role != User.Role.STUDENT:
			raise PermissionDenied
		return super().dispatch(request, *args, **kwargs)


class NotificationListView(StudentNotificationMixin, ListView):
	template_name = 'accounts/notifications.html'
	context_object_name = 'notifications'
	paginate_by = 20

	def get_queryset(self):
		return get_notifications(self.request.user)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['unread_notification_count'] = get_unread_count(self.request.user)
		return context


class NotificationOpenView(StudentNotificationMixin, View):
	def get(self, request, pk):
		notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
		if not notification.related_url:
			messages.info(request, 'This notification has no linked page.')
			return redirect('notifications')

		target = notification.related_url
		parsed_target = urlsplit(target)
		is_local_path = (
			target.startswith('/')
			and not target.startswith('//')
			and not target.startswith('/\\')
			and not parsed_target.scheme
			and not parsed_target.netloc
			and not any(ord(character) < 32 for character in target)
			and url_has_allowed_host_and_scheme(
				target,
				allowed_hosts={request.get_host()},
				require_https=request.is_secure(),
			)
		)
		if not is_local_path:
			messages.error(request, 'This notification link is invalid.')
			return redirect('notifications')

		mark_as_read(notification)
		return HttpResponseRedirect(target)


class NotificationReadView(StudentNotificationMixin, View):
	def post(self, request, pk):
		notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
		mark_as_read(notification)
		return redirect('notifications')


class NotificationMarkAllReadView(StudentNotificationMixin, View):
	def post(self, request):
		mark_all_as_read(request.user)
		return redirect('notifications')

# Create your views here.
