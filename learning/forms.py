from django import forms
from django.db.models import Max

from .models import Assignment, Evaluation, LearningDirection, LearningMaterial, LearningPlan, Lesson, LearningSession, Review, Submission


class LearningPlanForm(forms.ModelForm):
	class Meta:
		model = LearningPlan
		fields = ('learning_direction', 'title', 'description', 'status')
		widgets = {
			'learning_direction': forms.Select(attrs={'class': 'form-select'}),
			'title': forms.TextInput(attrs={'class': 'form-control'}),
			'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
			'status': forms.Select(attrs={'class': 'form-select'}),
		}

	def __init__(self, *args, teacher, **kwargs):
		super().__init__(*args, **kwargs)
		self.teacher = teacher
		self.fields['learning_direction'].queryset = LearningDirection.objects.filter(
			teacher__user=teacher,
			status=LearningDirection.Status.ACTIVE,
		).select_related('learner__user', 'skill')

	def clean(self):
		cleaned_data = super().clean()
		direction = cleaned_data.get('learning_direction')
		if direction and direction.teacher.user_id != self.teacher.pk:
			self.add_error('learning_direction', 'Select a direction you teach.')
		return cleaned_data


class LessonForm(forms.ModelForm):
	class Meta:
		model = Lesson
		fields = ('title', 'description', 'order', 'estimated_duration')
		labels = {'description': 'Lesson notes'}
		widgets = {
			'title': forms.TextInput(attrs={'class': 'form-control'}),
			'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
			'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
			'estimated_duration': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
		}

	def __init__(self, *args, learning_plan=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.learning_plan = learning_plan
		if self.learning_plan is None and self.instance.pk:
			self.learning_plan = self.instance.learning_plan
		if self.instance.pk is None and 'order' not in self.initial:
			last_order = Lesson.objects.filter(learning_plan=self.learning_plan).aggregate(last_order=Max('order'))['last_order'] or 0
			self.initial['order'] = last_order + 1

	def clean(self):
		cleaned_data = super().clean()
		order = cleaned_data.get('order')
		if self.learning_plan is not None and order is not None:
			lessons = Lesson.objects.filter(learning_plan=self.learning_plan, order=order)
			if self.instance.pk:
				lessons = lessons.exclude(pk=self.instance.pk)
			if lessons.exists():
				self.add_error('order', 'This lesson order is already used in the plan.')
		return cleaned_data


class LessonStatusForm(forms.ModelForm):
	class Meta:
		model = Lesson
		fields = ('status',)
		widgets = {'status': forms.Select(attrs={'class': 'form-select'})}


class LearningMaterialForm(forms.ModelForm):
	class Meta:
		model = LearningMaterial
		fields = ('title', 'description', 'material_type', 'external_url', 'file')
		labels = {'description': 'Notes / description'}
		widgets = {
			'title': forms.TextInput(attrs={'class': 'form-control'}),
			'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
			'material_type': forms.Select(attrs={'class': 'form-select'}),
			'external_url': forms.URLInput(attrs={
				'class': 'form-control',
				'placeholder': 'https://example.com/resource',
			}),
			'file': forms.ClearableFileInput(attrs={
				'class': 'form-control',
				'accept': '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip',
			}),
		}

	def __init__(self, *args, teacher, lesson=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.teacher = teacher
		self.lesson = lesson or (self.instance.lesson if self.instance.pk else None)

	def clean(self):
		cleaned_data = super().clean()
		material_type = cleaned_data.get('material_type')
		external_url = cleaned_data.get('external_url')
		uploaded_file = cleaned_data.get('file')

		if self.lesson and self.lesson.learning_plan.learning_direction.teacher.user_id != self.teacher.pk:
			raise forms.ValidationError('Only the lesson teacher can manage its materials.')

		if material_type == LearningMaterial.MaterialType.LINK:
			if not external_url:
				self.add_error('external_url', 'Enter a valid URL for this external link.')
			if uploaded_file:
				self.add_error('file', 'Clear the uploaded file when using an external link.')
		elif material_type == LearningMaterial.MaterialType.FILE:
			if not uploaded_file:
				self.add_error('file', 'Choose a file to upload.')
			if external_url:
				self.add_error('external_url', 'Clear the URL when uploading a file.')
		return cleaned_data


class AssignmentForm(forms.ModelForm):
	class Meta:
		model = Assignment
		fields = ('title', 'instructions', 'due_date', 'resource_file', 'status')
		widgets = {
			'title': forms.TextInput(attrs={'class': 'form-control'}),
			'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
			'due_date': forms.DateTimeInput(
				attrs={'class': 'form-control', 'type': 'datetime-local'},
				format='%Y-%m-%dT%H:%M',
			),
			'resource_file': forms.ClearableFileInput(attrs={
				'class': 'form-control',
				'accept': '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip',
			}),
			'status': forms.Select(attrs={'class': 'form-select'}),
		}

	def __init__(self, *args, teacher, lesson=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.teacher = teacher
		self.lesson = lesson or (self.instance.lesson if self.instance.pk else None)
		self.fields['due_date'].input_formats = ('%Y-%m-%dT%H:%M',)

	def clean(self):
		cleaned_data = super().clean()
		if self.lesson and self.lesson.learning_plan.learning_direction.teacher.user_id != self.teacher.pk:
			raise forms.ValidationError('Only the lesson teacher can manage this assignment.')
		return cleaned_data


class LearningSessionForm(forms.ModelForm):
	class Meta:
		model = LearningSession
		fields = ('title', 'description', 'lesson', 'scheduled_start', 'scheduled_end', 'meeting_url')
		widgets = {
			'title': forms.TextInput(attrs={'class': 'form-control'}),
			'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
			'lesson': forms.Select(attrs={'class': 'form-select'}),
			'scheduled_start': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
			'scheduled_end': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
			'meeting_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://meet.google.com/example'}),
		}

	def __init__(self, *args, direction=None, teacher=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.direction = direction
		self.teacher = teacher
		if direction is not None:
			self.fields['lesson'].queryset = Lesson.objects.filter(
				learning_plan__learning_direction=direction,
			).order_by('learning_plan__title', 'order')
			self.fields['lesson'].empty_label = 'General session (no lesson)'
			self.fields['lesson'].required = False
			if self.instance.pk is not None:
				self.instance.learning_direction = direction

		self.fields['scheduled_start'].input_formats = ('%Y-%m-%dT%H:%M',)
		self.fields['scheduled_end'].input_formats = ('%Y-%m-%dT%H:%M',)

	def clean(self):
		cleaned_data = super().clean()
		if self.direction and self.teacher and self.direction.teacher.user_id != self.teacher.pk:
			raise forms.ValidationError('Only the direction teacher can manage this session.')
		start = cleaned_data.get('scheduled_start')
		end = cleaned_data.get('scheduled_end')
		if start and end and end <= start:
			self.add_error('scheduled_end', 'The session end time must be after the start time.')
		if self.direction and start and end and self.instance.status == LearningSession.Status.SCHEDULED:
			conflicts = LearningSession.objects.filter(
				learning_direction=self.direction,
				status=LearningSession.Status.SCHEDULED,
			).exclude(pk=self.instance.pk)
			for other in conflicts:
				if start < other.scheduled_end and end > other.scheduled_start:
					self.add_error(None, 'This session overlaps with another scheduled session for this learning direction.')
					break
		return cleaned_data


class SubmissionForm(forms.ModelForm):
	class Meta:
		model = Submission
		fields = ('answer_text', 'file')
		widgets = {
			'answer_text': forms.Textarea(attrs={
				'class': 'form-control',
				'rows': 6,
				'placeholder': 'Write your answer here (optional if you attach a file)',
			}),
			'file': forms.ClearableFileInput(attrs={
				'class': 'form-control',
				'accept': '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.zip',
			}),
		}

	def clean(self):
		cleaned_data = super().clean()
		answer_text = cleaned_data.get('answer_text') or ''
		uploaded_file = cleaned_data.get('file')
		if not answer_text.strip() and not uploaded_file:
			raise forms.ValidationError('Write an answer or attach a file before saving.')
		return cleaned_data


class EvaluationForm(forms.ModelForm):
	class Meta:
		model = Evaluation
		fields = ('score', 'feedback')
		widgets = {
			'score': forms.NumberInput(attrs={
				'class': 'form-control',
				'min': 0,
				'max': 100,
				'step': '0.01',
				'placeholder': 'Optional, 0 to 100',
			}),
			'feedback': forms.Textarea(attrs={
				'class': 'form-control',
				'rows': 6,
				'placeholder': 'Feedback and suggestions for the learner',
			}),
		}

	def __init__(self, *args, submission, evaluator, **kwargs):
		super().__init__(*args, **kwargs)
		self.submission = submission
		self.evaluator = evaluator
		self.instance.submission = submission
		self.instance.evaluator = evaluator

	def clean(self):
		cleaned_data = super().clean()
		score = cleaned_data.get('score')
		feedback = cleaned_data.get('feedback') or ''
		if score is None and not feedback.strip():
			raise forms.ValidationError('Provide feedback or a score to complete the evaluation.')
		return cleaned_data


class ReviewForm(forms.ModelForm):
	class Meta:
		model = Review
		fields = ('rating', 'comment')
		widgets = {
			'rating': forms.Select(
				choices=((value, f'{value} / 5') for value in range(1, 6)),
				attrs={'class': 'form-select'},
			),
			'comment': forms.Textarea(attrs={
				'class': 'form-control',
				'rows': 4,
				'maxlength': 1000,
				'placeholder': 'Share optional feedback about this learning experience.',
			}),
		}