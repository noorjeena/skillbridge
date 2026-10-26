from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView

from accounts.models import User

from .forms import AssignmentForm, EvaluationForm, LearningMaterialForm, LearningPlanForm, LearningSessionForm, LessonForm, LessonStatusForm, ReviewForm, SubmissionForm
from .models import Assignment, Evaluation, LearningDirection, LearningMaterial, LearningMaterialAccess, LearningPlan, Lesson, LearningSession, Review, Submission
from .services import (
	create_review,
	notify_assignment_created,
	notify_assignment_submitted,
	notify_session_event,
	save_evaluation,
	update_review,
)


def _record_material_access(material, user):
	learner = user.student_profile
	direction = material.lesson.learning_plan.learning_direction
	if learner.pk != direction.learner_id:
		return
	LearningMaterialAccess.objects.get_or_create(material=material, learner=learner)
	if material.lesson.status == Lesson.Status.PENDING:
		material.lesson.status = Lesson.Status.IN_PROGRESS
		material.lesson.save(update_fields=('status', 'updated_at'))


def _refresh_lesson_status(lesson):
	active_assignments = list(lesson.assignments.filter(status=Assignment.Status.ACTIVE))
	if lesson.is_completed:
		new_status = Lesson.Status.COMPLETED
	elif active_assignments:
		new_status = Lesson.Status.IN_PROGRESS
	else:
		new_status = Lesson.Status.PENDING
	if lesson.status != new_status:
		lesson.status = new_status
		lesson.save(update_fields=('status', 'updated_at'))


class StudentRequiredMixin(LoginRequiredMixin):
	def dispatch(self, request, *args, **kwargs):
		if not request.user.is_authenticated:
			return self.handle_no_permission()
		if request.user.role != User.Role.STUDENT:
			raise PermissionDenied
		return super().dispatch(request, *args, **kwargs)


class DirectionSessionMixin:
	def get_direction(self):
		return get_object_or_404(
			LearningDirection.objects.filter(
				Q(teacher__user=self.request.user) | Q(learner__user=self.request.user),
				status=LearningDirection.Status.ACTIVE,
			),
			pk=self.kwargs['direction_pk'],
		)


class LearningDirectionListView(StudentRequiredMixin, TemplateView):
	template_name = 'learning/direction_list.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = self.request.user.student_profile
		directions = LearningDirection.objects.filter(
			Q(teacher=profile) | Q(learner=profile),
			status=LearningDirection.Status.ACTIVE,
		).select_related(
			'teacher__user', 'learner__user', 'skill', 'partnership',
		).prefetch_related(
			'learning_plans__lessons__assignments__submissions',
			'learning_plans__lessons__materials__learner_accesses',
			'sessions__lesson',
			Prefetch(
				'reviews',
				queryset=Review.objects.filter(reviewer=profile),
				to_attr='viewer_reviews',
			),
		)
		for direction in directions:
			direction.viewer_review = direction.viewer_reviews[0] if direction.viewer_reviews else None
			direction.can_review = (
				direction.learner_id == profile.pk
				and any(
					session.status == LearningSession.Status.COMPLETED
					for session in direction.sessions.all()
				)
			)
		context['directions'] = directions
		return context

class LearningPlanCreateView(StudentRequiredMixin, CreateView):
	model = LearningPlan
	form_class = LearningPlanForm
	template_name = 'learning/plan_form.html'
	success_url = reverse_lazy('learning:directions')

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs['teacher'] = self.request.user
		return kwargs

	def form_valid(self, form):
		form.instance.created_by = self.request.user
		response = super().form_valid(form)
		return redirect('learning:plan-detail', pk=self.object.pk)


class TeacherPlanQuerysetMixin:
	def get_queryset(self):
		return LearningPlan.objects.filter(learning_direction__teacher__user=self.request.user)


class LearningPlanUpdateView(StudentRequiredMixin, TeacherPlanQuerysetMixin, UpdateView):
	model = LearningPlan
	form_class = LearningPlanForm
	template_name = 'learning/plan_form.html'
	success_url = reverse_lazy('learning:directions')

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs['teacher'] = self.request.user
		return kwargs


class LearningPlanDeleteView(StudentRequiredMixin, TeacherPlanQuerysetMixin, DeleteView):
	model = LearningPlan
	template_name = 'learning/confirm_delete.html'
	success_url = reverse_lazy('learning:directions')
	extra_context = {'item_type': 'learning plan'}


class LearningPlanDetailView(StudentRequiredMixin, DetailView):
	model = LearningPlan
	template_name = 'learning/plan_detail.html'
	context_object_name = 'plan'

	def get_queryset(self):
		return LearningPlan.objects.filter(
			Q(learning_direction__teacher__user=self.request.user)
			| Q(learning_direction__learner__user=self.request.user, status=LearningPlan.Status.ACTIVE),
		).select_related(
			'learning_direction__teacher__user',
			'learning_direction__learner__user',
			'learning_direction__skill',
		).prefetch_related(
			'lessons__assignments__submissions',
			'lessons__materials__learner_accesses',
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['is_teacher'] = self.object.learning_direction.teacher.user_id == self.request.user.id
		context['is_learner'] = self.object.learning_direction.learner.user_id == self.request.user.id
		learner = self.object.learning_direction.learner
		all_lessons = list(self.object.lessons.all())
		for lesson in all_lessons:
			lesson.active_assignments = [
				assignment for assignment in lesson.assignments.all()
				if assignment.status == Assignment.Status.ACTIVE
			]
			lesson.visible_assignments = (
				lesson.assignments.all()
				if context['is_teacher']
				else lesson.active_assignments
			)
			for assignment in lesson.visible_assignments:
				assignment.learner_submission = next(
					(
						submission for submission in assignment.submissions.all()
						if submission.learner_id == learner.pk
					),
					None,
				)
			lesson.submitted_assignment_count = sum(
				any(
					submission.learner_id == learner.pk
					and submission.status in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED)
					for submission in assignment.submissions.all()
				)
				for assignment in lesson.active_assignments
			)
			lesson.accessible_materials = list(lesson.materials.all())
			lesson.file_material_count = sum(
				material.material_type == LearningMaterial.MaterialType.FILE
				for material in lesson.accessible_materials
			)
			lesson.accessed_material_ids = {
				material.pk
				for material in lesson.accessible_materials
				if any(access.learner_id == learner.pk for access in material.learner_accesses.all())
			}
			lesson.accessed_material_count = len(lesson.accessed_material_ids)
			lesson.learner_is_completed = bool(lesson.active_assignments) and (
				lesson.submitted_assignment_count == len(lesson.active_assignments)
			)
			lesson.learner_progress_status = (
				Lesson.Status.COMPLETED if lesson.learner_is_completed
				else Lesson.Status.IN_PROGRESS if lesson.submitted_assignment_count or lesson.accessed_material_count
				else Lesson.Status.PENDING
			)
			lesson.learner_progress_label = dict(Lesson.Status.choices)[lesson.learner_progress_status]
		context['plan_file_count'] = sum(lesson.file_material_count for lesson in all_lessons)
		context['plan_accessed_file_count'] = sum(lesson.accessed_material_count for lesson in all_lessons)
		return context


class TeacherLessonQuerysetMixin:
	def get_queryset(self):
		return Lesson.objects.filter(learning_plan__learning_direction__teacher__user=self.request.user)


class LessonCreateView(StudentRequiredMixin, CreateView):
	model = Lesson
	form_class = LessonForm
	template_name = 'learning/lesson_form.html'

	def get_plan(self):
		return get_object_or_404(
			LearningPlan,
			pk=self.kwargs['plan_pk'],
			learning_direction__teacher__user=self.request.user,
		)

	def get_initial(self):
		initial = super().get_initial()
		last_order = self.get_plan().lessons.aggregate(last_order=Max('order'))['last_order'] or 0
		initial['order'] = last_order + 1
		return initial

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs['learning_plan'] = self.get_plan()
		return kwargs

	def form_valid(self, form):
		form.instance.learning_plan = self.get_plan()
		return super().form_valid(form)

	def get_success_url(self):
		return reverse('learning:plan-detail', args=(self.object.learning_plan_id,))


class LessonUpdateView(StudentRequiredMixin, TeacherLessonQuerysetMixin, UpdateView):
	model = Lesson
	form_class = LessonForm
	template_name = 'learning/lesson_form.html'

	def get_success_url(self):
		return reverse('learning:plan-detail', args=(self.object.learning_plan_id,))


class LessonDeleteView(StudentRequiredMixin, TeacherLessonQuerysetMixin, DeleteView):
	model = Lesson
	template_name = 'learning/confirm_delete.html'
	extra_context = {'item_type': 'lesson'}

	def get_success_url(self):
		return reverse('learning:plan-detail', args=(self.object.learning_plan_id,))


class LessonDetailView(StudentRequiredMixin, DetailView):
	model = Lesson
	template_name = 'learning/lesson_detail.html'
	context_object_name = 'lesson'

	def get_queryset(self):
		return Lesson.objects.filter(
			Q(learning_plan__learning_direction__teacher__user=self.request.user)
			| Q(
				learning_plan__learning_direction__learner__user=self.request.user,
				learning_plan__status=LearningPlan.Status.ACTIVE,
			),
		).select_related(
			'learning_plan__learning_direction__teacher__user',
			'learning_plan__learning_direction__learner__user',
			'learning_plan__learning_direction__skill',
		).prefetch_related('materials')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['is_teacher'] = self.object.learning_plan.learning_direction.teacher.user_id == self.request.user.id
		context['is_learner'] = self.object.learning_plan.learning_direction.learner.user_id == self.request.user.id
		context['materials'] = self.object.materials.all()
		assignments = self.object.assignments.all()
		if not context['is_teacher']:
			assignments = assignments.filter(status=Assignment.Status.ACTIVE)
		context['assignments'] = assignments
		learner = self.object.learning_plan.learning_direction.learner
		accessed_material_ids = set(
			LearningMaterialAccess.objects.filter(
				learner=learner,
				material__lesson=self.object,
			).values_list('material_id', flat=True)
		)
		active_assignments = list(self.object.assignments.filter(status=Assignment.Status.ACTIVE))
		submitted_assignments = sum(
			assignment.submissions.filter(
				learner=learner,
				status__in=(Submission.Status.SUBMITTED, Submission.Status.EVALUATED),
			).exists()
			for assignment in active_assignments
		)
		context['accessed_material_ids'] = accessed_material_ids
		context['material_access_count'] = len(accessed_material_ids)
		context['material_count'] = self.object.materials.filter(
			material_type=LearningMaterial.MaterialType.FILE,
		).count()
		context['active_assignment_count'] = len(active_assignments)
		context['submitted_assignment_count'] = submitted_assignments
		context['lesson_progress_status'] = self.object.progress_status
		context['lesson_progress_label'] = dict(Lesson.Status.choices)[self.object.progress_status]
		return context


class LessonStatusUpdateView(StudentRequiredMixin, View):
	def post(self, request, pk):
		lesson = get_object_or_404(
			Lesson,
			pk=pk,
			learning_plan__learning_direction__learner__user=request.user,
		)
		form = LessonStatusForm(request.POST, instance=lesson)
		if not form.is_valid():
			messages.error(request, 'Choose a valid lesson status.')
		elif form.cleaned_data['status'] == Lesson.Status.COMPLETED and not lesson.is_completed:
			messages.error(request, 'Complete all active lesson assignments before marking this lesson complete.')
		elif lesson.is_completed and form.cleaned_data['status'] != Lesson.Status.COMPLETED:
			messages.error(request, 'A completed lesson cannot be moved back to an earlier status.')
		else:
			form.save()
			messages.success(request, 'Lesson progress updated.')
		return redirect('learning:lesson-detail', pk=lesson.pk)


class LessonMaterialsMixin:
	def get_lesson(self):
		return get_object_or_404(
			Lesson.objects.filter(
				Q(learning_plan__learning_direction__teacher__user=self.request.user)
				| Q(
					learning_plan__learning_direction__learner__user=self.request.user,
					learning_plan__status=LearningPlan.Status.ACTIVE,
				),
			),
			pk=self.kwargs['lesson_pk'],
		)


class LessonMaterialListView(StudentRequiredMixin, LessonMaterialsMixin, ListView):
	model = LearningMaterial
	template_name = 'learning/material_list.html'
	context_object_name = 'materials'

	def get_queryset(self):
		self.lesson = self.get_lesson()
		return LearningMaterial.objects.filter(lesson=self.lesson).select_related('created_by')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.lesson
		context['is_teacher'] = self.lesson.learning_plan.learning_direction.teacher.user_id == self.request.user.id
		return context


class LessonMaterialCreateView(StudentRequiredMixin, LessonMaterialsMixin, CreateView):
	model = LearningMaterial
	form_class = LearningMaterialForm
	template_name = 'learning/material_form.html'

	def get_lesson(self):
		return get_object_or_404(
			Lesson,
			pk=self.kwargs['lesson_pk'],
			learning_plan__learning_direction__teacher__user=self.request.user,
		)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update(teacher=self.request.user, lesson=self.get_lesson())
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.get_lesson()
		return context

	def form_valid(self, form):
		form.instance.lesson = self.get_lesson()
		form.instance.created_by = self.request.user
		return super().form_valid(form)

	def get_success_url(self):
		return reverse('learning:lesson-materials', args=(self.object.lesson_id,))


class TeacherMaterialQuerysetMixin:
	def get_queryset(self):
		return LearningMaterial.objects.filter(
			lesson__learning_plan__learning_direction__teacher__user=self.request.user,
			created_by=self.request.user,
		).select_related('lesson')


class LearningMaterialUpdateView(StudentRequiredMixin, TeacherMaterialQuerysetMixin, UpdateView):
	model = LearningMaterial
	form_class = LearningMaterialForm
	template_name = 'learning/material_form.html'

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update(teacher=self.request.user, lesson=self.object.lesson)
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.object.lesson
		return context

	def get_success_url(self):
		return reverse('learning:lesson-materials', args=(self.object.lesson_id,))


class LearningMaterialDeleteView(StudentRequiredMixin, TeacherMaterialQuerysetMixin, DeleteView):
	model = LearningMaterial
	template_name = 'learning/material_confirm_delete.html'

	def get_success_url(self):
		return reverse('learning:lesson-materials', args=(self.object.lesson_id,))


class LearningMaterialFileView(StudentRequiredMixin, View):
	def get(self, request, pk):
		material = get_object_or_404(
			LearningMaterial.objects.filter(
				Q(lesson__learning_plan__learning_direction__teacher__user=request.user)
				| Q(
					lesson__learning_plan__learning_direction__learner__user=request.user,
					lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
				),
				material_type=LearningMaterial.MaterialType.FILE,
			),
			pk=pk,
		)
		if not material.file:
			raise Http404
		_record_material_access(material, request.user)
		return FileResponse(
			material.file.open('rb'),
			as_attachment=request.GET.get('download') in {'1', 'true', 'download'},
			filename=material.file.name.rsplit('/', 1)[-1],
		)


class ProtectedLearningMaterialStorageView(StudentRequiredMixin, View):
	def get(self, request, filepath):
		filepath = filepath.replace('\\', '/').lstrip('/')
		if not filepath or '..' in filepath.split('/'):
			raise Http404
		material = get_object_or_404(
			LearningMaterial.objects.filter(
				Q(lesson__learning_plan__learning_direction__teacher__user=request.user)
				| Q(
					lesson__learning_plan__learning_direction__learner__user=request.user,
					lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
				),
				file__endswith=filepath,
				material_type=LearningMaterial.MaterialType.FILE,
			),
		)
		_record_material_access(material, request.user)
		return FileResponse(
			material.file.open('rb'),
			as_attachment=request.GET.get('download') in {'1', 'true', 'download'},
			filename=material.file.name.rsplit('/', 1)[-1],
		)


class AssignmentResourceFileView(StudentRequiredMixin, View):
	def get(self, request, pk):
		if request.user.is_staff:
			assignment = get_object_or_404(Assignment, pk=pk)
		else:
			assignment = get_object_or_404(
				Assignment.objects.filter(
					Q(lesson__learning_plan__learning_direction__teacher__user=request.user)
					| Q(
						lesson__learning_plan__learning_direction__learner__user=request.user,
						status__in=(Assignment.Status.ACTIVE, Assignment.Status.CLOSED),
						lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
						lesson__learning_plan__learning_direction__status=LearningDirection.Status.ACTIVE,
					),
				),
				pk=pk,
			)
		if not assignment.resource_file:
			raise Http404
		return FileResponse(
			assignment.resource_file.open('rb'),
			as_attachment=request.GET.get('download') in {'1', 'true', 'download'},
			filename=assignment.resource_file.name.rsplit('/', 1)[-1],
		)


class ProtectedAssignmentResourceStorageView(StudentRequiredMixin, View):
	def get(self, request, filepath):
		filepath = filepath.replace('\\', '/').lstrip('/')
		if not filepath or '..' in filepath.split('/'):
			raise Http404
		if request.user.is_staff:
			assignment = get_object_or_404(
				Assignment.objects.filter(resource_file__endswith=filepath),
			)
		else:
			assignment = get_object_or_404(
				Assignment.objects.filter(
					Q(lesson__learning_plan__learning_direction__teacher__user=request.user)
					| Q(
						lesson__learning_plan__learning_direction__learner__user=request.user,
						status__in=(Assignment.Status.ACTIVE, Assignment.Status.CLOSED),
						lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
						lesson__learning_plan__learning_direction__status=LearningDirection.Status.ACTIVE,
					),
					resource_file__endswith=filepath,
				),
			)
		if not assignment.resource_file:
			raise Http404
		return FileResponse(
			assignment.resource_file.open('rb'),
			as_attachment=True,
			filename=assignment.resource_file.name.rsplit('/', 1)[-1],
		)


class LessonAssignmentsView(StudentRequiredMixin, LessonMaterialsMixin, ListView):
	model = Assignment
	template_name = 'learning/assignment_list.html'
	context_object_name = 'assignments'

	def get_queryset(self):
		self.lesson = self.get_lesson()
		assignments = Assignment.objects.filter(lesson=self.lesson).select_related('created_by')
		if self.lesson.learning_plan.learning_direction.learner.user_id == self.request.user.id:
			assignments = assignments.filter(status=Assignment.Status.ACTIVE)
		return assignments

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.lesson
		context['is_teacher'] = self.lesson.learning_plan.learning_direction.teacher.user_id == self.request.user.id
		return context


class LessonAssignmentCreateView(StudentRequiredMixin, CreateView):
	model = Assignment
	form_class = AssignmentForm
	template_name = 'learning/assignment_form.html'

	def get_lesson(self):
		return get_object_or_404(
			Lesson,
			pk=self.kwargs['lesson_pk'],
			learning_plan__learning_direction__teacher__user=self.request.user,
		)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update(teacher=self.request.user, lesson=self.get_lesson())
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.get_lesson()
		return context

	def form_valid(self, form):
		form.instance.lesson = self.get_lesson()
		form.instance.created_by = self.request.user
		response = super().form_valid(form)
		_refresh_lesson_status(self.object.lesson)
		notify_assignment_created(self.object)
		return response

	def get_success_url(self):
		return reverse('learning:assignment-detail', args=(self.object.pk,))


class TeacherAssignmentQuerysetMixin:
	def get_queryset(self):
		return Assignment.objects.filter(
			lesson__learning_plan__learning_direction__teacher__user=self.request.user,
			created_by=self.request.user,
		).select_related('lesson__learning_plan__learning_direction__teacher__user')


class AssignmentUpdateView(StudentRequiredMixin, TeacherAssignmentQuerysetMixin, UpdateView):
	model = Assignment
	form_class = AssignmentForm
	template_name = 'learning/assignment_form.html'

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update(teacher=self.request.user, lesson=self.object.lesson)
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['lesson'] = self.object.lesson
		return context

	def form_valid(self, form):
		previous_status = form.initial['status']
		response = super().form_valid(form)
		_refresh_lesson_status(self.object.lesson)
		if previous_status != Assignment.Status.ACTIVE and self.object.status == Assignment.Status.ACTIVE:
			notify_assignment_created(self.object)
		return response

	def get_success_url(self):
		return reverse('learning:assignment-detail', args=(self.object.pk,))


class AssignmentDeleteView(StudentRequiredMixin, TeacherAssignmentQuerysetMixin, DeleteView):
	model = Assignment
	template_name = 'learning/assignment_confirm_delete.html'

	def get_success_url(self):
		return reverse('learning:lesson-assignments', args=(self.object.lesson_id,))

	def form_valid(self, form):
		lesson = self.object.lesson
		response = super().form_valid(form)
		_refresh_lesson_status(lesson)
		return response


class AssignmentDetailView(StudentRequiredMixin, DetailView):
	model = Assignment
	template_name = 'learning/assignment_detail.html'
	context_object_name = 'assignment'

	def get_queryset(self):
		return Assignment.objects.filter(
			Q(lesson__learning_plan__learning_direction__teacher__user=self.request.user)
			| Q(
				lesson__learning_plan__learning_direction__learner__user=self.request.user,
				status__in=(Assignment.Status.ACTIVE, Assignment.Status.CLOSED),
				lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
				lesson__learning_plan__learning_direction__status=LearningDirection.Status.ACTIVE,
			),
		).select_related(
			'lesson__learning_plan__learning_direction__teacher__user',
			'lesson__learning_plan__learning_direction__learner__user',
			'lesson__learning_plan__learning_direction__skill',
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		assignment = self.object
		profile = self.request.user.student_profile
		context['is_teacher'] = assignment.lesson.learning_plan.learning_direction.teacher_id == profile.pk
		if context['is_teacher']:
			context['submissions'] = assignment.submissions.select_related('learner__user', 'evaluation__evaluator')
		else:
			submission = assignment.submissions.filter(learner=profile).first()
			context['submission'] = submission
			context['evaluation'] = getattr(submission, 'evaluation', None) if submission else None
			context['submission_form'] = SubmissionForm(instance=submission if submission and submission.status == Submission.Status.DRAFT else None)
			context['can_submit'] = assignment.status == Assignment.Status.ACTIVE and not (
				submission and submission.status in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED)
			)
		return context


class LearningSessionCreateView(StudentRequiredMixin, CreateView):
	model = LearningSession
	form_class = LearningSessionForm
	template_name = 'learning/session_form.html'

	def get_direction(self):
		return get_object_or_404(
			LearningDirection.objects.filter(
				teacher__user=self.request.user,
				status=LearningDirection.Status.ACTIVE,
			),
			pk=self.kwargs['direction_pk'],
		)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update({'direction': self.get_direction(), 'teacher': self.request.user})
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['direction'] = self.get_direction()
		return context

	def form_valid(self, form):
		form.instance.learning_direction = self.get_direction()
		form.instance.created_by = self.request.user
		response = super().form_valid(form)
		notify_session_event(
			self.object,
			status_change=LearningSession.Status.SCHEDULED,
			actor=self.request.user,
		)
		return response

	def get_success_url(self):
		return reverse('learning:session-detail', args=(self.object.pk,))


class LearningSessionDetailView(StudentRequiredMixin, DetailView):
	model = LearningSession
	template_name = 'learning/session_detail.html'
	context_object_name = 'session'

	def get_queryset(self):
		return LearningSession.objects.filter(
			Q(learning_direction__teacher__user=self.request.user)
			| Q(learning_direction__learner__user=self.request.user),
		).select_related('learning_direction__teacher__user', 'learning_direction__learner__user', 'learning_direction__skill', 'lesson__learning_plan')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['is_teacher'] = self.object.learning_direction.teacher.user_id == self.request.user.id
		context['is_learner'] = self.object.learning_direction.learner.user_id == self.request.user.id
		context['can_join'] = bool(self.object.meeting_url) and self.object.is_live
		return context


class LearningSessionUpdateView(StudentRequiredMixin, UpdateView):
	model = LearningSession
	form_class = LearningSessionForm
	template_name = 'learning/session_form.html'

	def get_queryset(self):
		return LearningSession.objects.filter(learning_direction__teacher__user=self.request.user).select_related('learning_direction__teacher__user', 'learning_direction__learner__user', 'lesson')

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs.update({'direction': self.object.learning_direction, 'teacher': self.request.user})
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['direction'] = self.object.learning_direction
		return context

	def form_valid(self, form):
		changed = bool(form.changed_data)
		response = super().form_valid(form)
		if changed:
			notify_session_event(
				self.object,
				status_change='UPDATED',
				actor=self.request.user,
			)
		return response

	def get_success_url(self):
		return reverse('learning:session-detail', args=(self.object.pk,))


class LearningSessionDeleteView(StudentRequiredMixin, DeleteView):
	model = LearningSession
	template_name = 'learning/confirm_delete.html'
	extra_context = {'item_type': 'session'}

	def get_queryset(self):
		return LearningSession.objects.filter(learning_direction__teacher__user=self.request.user)

	def get_success_url(self):
		return reverse('learning:directions')


class LearningSessionStatusUpdateView(StudentRequiredMixin, View):
	def post(self, request, pk):
		session = get_object_or_404(
			LearningSession.objects.filter(learning_direction__teacher__user=request.user),
			pk=pk,
		)
		action = request.POST.get('action')
		if action == 'cancel':
			was_cancelled = session.status == LearningSession.Status.CANCELLED
			session.status = LearningSession.Status.CANCELLED
			session.save()
			if not was_cancelled:
				notify_session_event(
					session,
					status_change=LearningSession.Status.CANCELLED,
					actor=request.user,
				)
			messages.success(request, 'Session cancelled.')
			return redirect('learning:session-detail', pk=session.pk)
		if action == 'complete':
			was_completed = session.status == LearningSession.Status.COMPLETED
			session.status = LearningSession.Status.COMPLETED
			session.save()
			if not was_completed:
				notify_session_event(
					session,
					status_change=LearningSession.Status.COMPLETED,
					actor=request.user,
				)
			messages.success(request, 'Session marked as completed.')
			return redirect('learning:session-detail', pk=session.pk)
		messages.error(request, 'Choose a valid session action.')
		return redirect('learning:session-detail', pk=session.pk)


class ReviewCreateView(StudentRequiredMixin, FormView):
	form_class = ReviewForm
	template_name = 'learning/review_form.html'

	def get_direction(self):
		return get_object_or_404(
			LearningDirection.objects.select_related('teacher__user', 'learner__user', 'skill'),
			pk=self.kwargs['direction_pk'],
			learner__user=self.request.user,
		)

	def review_is_eligible(self):
		return any(
			session.status == LearningSession.Status.COMPLETED
			for session in self.direction.sessions.all()
		)

	def get(self, request, *args, **kwargs):
		self.direction = self.get_direction()
		if not self.review_is_eligible():
			messages.info(request, 'You can review your teacher after a learning session is completed.')
			return redirect('learning:directions')
		existing_review = Review.objects.filter(
			learning_direction=self.direction,
			reviewer=self.direction.learner,
		).first()
		if existing_review:
			return redirect('learning:review-edit', pk=existing_review.pk)
		return super().get(request, *args, **kwargs)

	def post(self, request, *args, **kwargs):
		self.direction = self.get_direction()
		if not self.review_is_eligible():
			messages.info(request, 'You can review your teacher after a learning session is completed.')
			return redirect('learning:directions')
		return super().post(request, *args, **kwargs)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['direction'] = self.direction
		return context

	def form_valid(self, form):
		try:
			create_review(
				self.direction.pk,
				self.request.user,
				rating=form.cleaned_data['rating'],
				comment=form.cleaned_data['comment'],
			)
		except ValidationError as error:
			form.add_error(None, error.messages[0])
			return self.form_invalid(form)
		messages.success(self.request, 'Your review was submitted.')
		return redirect('learning:directions')

	def form_invalid(self, form):
		return self.render_to_response(self.get_context_data(form=form))


class ReviewUpdateView(StudentRequiredMixin, UpdateView):
	model = Review
	form_class = ReviewForm
	template_name = 'learning/review_form.html'

	def get_queryset(self):
		return Review.objects.filter(reviewer__user=self.request.user).select_related(
			'learning_direction__teacher__user',
			'learning_direction__learner__user',
			'learning_direction__skill',
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['direction'] = self.object.learning_direction
		return context

	def form_valid(self, form):
		try:
			update_review(
				self.object.pk,
				self.request.user,
				rating=form.cleaned_data['rating'],
				comment=form.cleaned_data['comment'],
			)
		except ValidationError as error:
			form.add_error(None, error.messages[0])
			return self.form_invalid(form)
		messages.success(self.request, 'Your review was updated.')
		return redirect('learning:directions')


class ReviewDeleteView(StudentRequiredMixin, DeleteView):
	model = Review
	template_name = 'learning/confirm_delete.html'
	extra_context = {'item_type': 'review'}
	success_url = reverse_lazy('learning:directions')

	def get_queryset(self):
		return Review.objects.filter(reviewer__user=self.request.user).select_related(
			'learning_direction__skill',
		)


class LearningSessionListView(StudentRequiredMixin, TemplateView):
	template_name = 'learning/session_list.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		profile = self.request.user.student_profile
		sessions = LearningSession.objects.filter(
			Q(learning_direction__teacher=profile) | Q(learning_direction__learner=profile),
		).select_related('learning_direction__teacher__user', 'learning_direction__learner__user', 'learning_direction__skill', 'lesson')
		context['upcoming'] = sessions.filter(status=LearningSession.Status.SCHEDULED, scheduled_end__gte=timezone.now())
		context['past'] = sessions.filter(Q(status=LearningSession.Status.COMPLETED) | Q(status=LearningSession.Status.SCHEDULED, scheduled_end__lt=timezone.now()))
		context['cancelled'] = sessions.filter(status=LearningSession.Status.CANCELLED)
		return context


class AssignmentSubmissionView(StudentRequiredMixin, FormView):
	form_class = SubmissionForm
	template_name = 'learning/assignment_detail.html'

	def get_assignment(self):
		return get_object_or_404(
			Assignment,
			pk=self.kwargs['pk'],
			lesson__learning_plan__learning_direction__learner__user=self.request.user,
			lesson__learning_plan__learning_direction__status=LearningDirection.Status.ACTIVE,
			lesson__learning_plan__status=LearningPlan.Status.ACTIVE,
			status=Assignment.Status.ACTIVE,
		)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		assignment = self.get_assignment()
		profile = self.request.user.student_profile
		submission = Submission.objects.filter(assignment=assignment, learner=profile).first()
		kwargs['instance'] = submission
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		assignment = self.get_assignment()
		profile = self.request.user.student_profile
		submission = Submission.objects.filter(assignment=assignment, learner=profile).first()
		context.update({
			'assignment': assignment,
			'is_teacher': False,
			'submission': submission,
			'can_submit': not submission or submission.status == Submission.Status.DRAFT,
		})
		return context

	def form_valid(self, form):
		assignment = self.get_assignment()
		profile = self.request.user.student_profile
		submission, _ = Submission.objects.get_or_create(assignment=assignment, learner=profile)
		if submission.status in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED):
			messages.error(self.request, 'This submission cannot be changed once it has been submitted or evaluated.')
			return redirect('learning:assignment-detail', pk=assignment.pk)

		form.instance.pk = submission.pk
		form.instance.assignment = assignment
		form.instance.learner = profile
		action = self.request.POST.get('action')
		if action not in ('draft', 'submit'):
			form.add_error(None, 'Choose Save Draft or Submit.')
			return self.form_invalid(form)
		if action == 'submit':
			form.instance.status = Submission.Status.SUBMITTED
			form.instance.submitted_at = timezone.now()
		else:
			form.instance.status = Submission.Status.DRAFT
			form.instance.submitted_at = None
		form.save()
		_refresh_lesson_status(assignment.lesson)
		if action == 'submit':
			notify_assignment_submitted(submission)
		messages.success(
			self.request,
			'Submission received.' if action == 'submit' else 'Draft saved.',
		)
		return redirect('learning:assignment-detail', pk=assignment.pk)

	def form_invalid(self, form):
		assignment = self.get_assignment()
		profile = self.request.user.student_profile
		submission = Submission.objects.filter(assignment=assignment, learner=profile).first()
		context = {
			'assignment': assignment,
			'is_teacher': False,
			'submission': submission,
			'submission_form': form,
			'can_submit': True,
		}
		return self.render_to_response(context)


class TeacherAssignmentSubmissionsView(StudentRequiredMixin, ListView):
	model = Submission
	template_name = 'learning/assignment_submissions.html'
	context_object_name = 'submissions'

	def get_queryset(self):
		self.assignment = get_object_or_404(
			Assignment,
			pk=self.kwargs['pk'],
			lesson__learning_plan__learning_direction__teacher__user=self.request.user,
		)
		return Submission.objects.filter(assignment=self.assignment).select_related('learner__user', 'evaluation__evaluator')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['assignment'] = self.assignment
		return context


class SubmissionDetailView(StudentRequiredMixin, DetailView):
	model = Submission
	template_name = 'learning/submission_detail.html'
	context_object_name = 'submission'

	def get_queryset(self):
		return Submission.objects.filter(
			Q(learner__user=self.request.user)
			| Q(assignment__lesson__learning_plan__learning_direction__teacher__user=self.request.user),
		).select_related('learner__user', 'assignment__lesson', 'evaluation__evaluator')

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['is_teacher'] = self.object.assignment.lesson.learning_plan.learning_direction.teacher.user_id == self.request.user.id
		context['evaluation'] = getattr(self.object, 'evaluation', None)
		return context


class SubmissionEvaluationView(StudentRequiredMixin, FormView):
	form_class = EvaluationForm
	template_name = 'learning/evaluation_form.html'

	def get_submission(self):
		return get_object_or_404(
			Submission.objects.filter(
				assignment__lesson__learning_plan__learning_direction__teacher__user=self.request.user,
				status__in=(Submission.Status.SUBMITTED, Submission.Status.EVALUATED),
			),
			pk=self.kwargs['pk'],
		)

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		submission = self.get_submission()
		evaluation = getattr(submission, 'evaluation', None)
		kwargs.update({
			'instance': evaluation or Evaluation(submission=submission),
			'submission': submission,
			'evaluator': self.request.user,
		})
		return kwargs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['submission'] = self.get_submission()
		context['evaluation'] = getattr(context['submission'], 'evaluation', None)
		return context

	def form_valid(self, form):
		submission = self.get_submission()
		try:
			evaluation = save_evaluation(
				submission.pk,
				self.request.user,
				score=form.cleaned_data['score'],
				feedback=form.cleaned_data['feedback'],
			)
		except ValidationError as error:
			form.add_error(None, error.messages[0])
			return self.form_invalid(form)

		messages.success(self.request, 'Evaluation saved.')
		return redirect('learning:submission-detail', pk=evaluation.submission_id)

	def form_invalid(self, form):
		context = self.get_context_data(form=form)
		return self.render_to_response(context)


class SubmissionFileView(StudentRequiredMixin, View):
	def get(self, request, pk):
		submission = get_object_or_404(
			Submission.objects.filter(
				Q(learner__user=request.user)
				| Q(assignment__lesson__learning_plan__learning_direction__teacher__user=request.user),
			),
			pk=pk,
		)
		if not submission.file:
			raise Http404
		return FileResponse(
			submission.file.open('rb'),
			as_attachment=True,
			filename=submission.file.name.rsplit('/', 1)[-1],
		)


class ProtectedSubmissionStorageView(StudentRequiredMixin, View):
	def get(self, request, filepath):
		filepath = filepath.replace('\\', '/').lstrip('/')
		if not filepath or '..' in filepath.split('/'):
			raise Http404
		stored_name = f'assignment_submissions/{filepath}'
		submission = get_object_or_404(
			Submission.objects.filter(
				Q(learner__user=request.user)
				| Q(assignment__lesson__learning_plan__learning_direction__teacher__user=request.user),
				file=stored_name,
			),
		)
		return FileResponse(
			submission.file.open('rb'),
			as_attachment=True,
			filename=submission.file.name.rsplit('/', 1)[-1],
		)
