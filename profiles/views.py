from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import DetailView, UpdateView

from .forms import StudentProfileForm
from .models import StudentProfile


class ProfileDetailView(LoginRequiredMixin, DetailView):
	model = StudentProfile
	template_name = 'profiles/profile_detail.html'
	context_object_name = 'profile'

	def get_object(self, queryset=None):
		return get_object_or_404(StudentProfile, user=self.request.user)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['offered_skills'] = self.object.offered_skills.select_related('skill').order_by('skill__name')
		context['learning_skills'] = self.object.learning_skills.select_related('skill').order_by('skill__name')
		context['reviews'] = self.object.received_reviews.select_related(
			'reviewer__user',
			'learning_direction__skill',
		)
		context['rating_average'] = self.object.average_rating
		context['review_count'] = self.object.review_count
		return context


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
	model = StudentProfile
	form_class = StudentProfileForm
	template_name = 'profiles/profile_form.html'
	context_object_name = 'profile'
	success_url = reverse_lazy('profile-detail')

	def get_object(self, queryset=None):
		return get_object_or_404(StudentProfile, user=self.request.user)

# Create your views here.
