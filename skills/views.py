from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from profiles.models import StudentProfile

from .forms import LearningSkillForm, OfferedSkillForm
from .models import LearningSkill, OfferedSkill


class SkillListView(LoginRequiredMixin, TemplateView):
	template_name = 'skills/skill_list.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = get_object_or_404(StudentProfile, user=self.request.user)
		context['offered_skills'] = profile.offered_skills.select_related('skill').order_by('skill__name')
		context['learning_skills'] = profile.learning_skills.select_related('skill').order_by('skill__name')
		return context


class ProfileSkillCreateView(LoginRequiredMixin, CreateView):
	def get_profile(self):
		return get_object_or_404(StudentProfile, user=self.request.user)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs['profile'] = self.get_profile()
		return kwargs

	def form_valid(self, form):
		form.instance.profile = self.get_profile()
		return super().form_valid(form)


class OwnedProfileSkillView(LoginRequiredMixin):
	def get_queryset(self):
		return self.model.objects.filter(profile__user=self.request.user)


class OfferedSkillCreateView(ProfileSkillCreateView):
	model = OfferedSkill
	form_class = OfferedSkillForm
	template_name = 'skills/skill_form.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'form_title': 'Add a teaching skill', 'submit_label': 'Add Teaching Skill'}


class OfferedSkillUpdateView(OwnedProfileSkillView, UpdateView):
	model = OfferedSkill
	form_class = OfferedSkillForm
	template_name = 'skills/skill_form.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'form_title': 'Edit teaching skill', 'submit_label': 'Save Changes'}


class OfferedSkillDeleteView(OwnedProfileSkillView, DeleteView):
	model = OfferedSkill
	template_name = 'skills/skill_confirm_delete.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'record_type': 'teaching skill'}


class LearningSkillCreateView(ProfileSkillCreateView):
	model = LearningSkill
	form_class = LearningSkillForm
	template_name = 'skills/skill_form.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'form_title': 'Add a learning skill', 'submit_label': 'Add Learning Skill'}


class LearningSkillUpdateView(OwnedProfileSkillView, UpdateView):
	model = LearningSkill
	form_class = LearningSkillForm
	template_name = 'skills/skill_form.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'form_title': 'Edit learning skill', 'submit_label': 'Save Changes'}


class LearningSkillDeleteView(OwnedProfileSkillView, DeleteView):
	model = LearningSkill
	template_name = 'skills/skill_confirm_delete.html'
	success_url = reverse_lazy('skills:index')
	extra_context = {'record_type': 'learning skill'}
