from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from matching.models import LearningPartnership
from skills.models import LearningSkill, OfferedSkill, Skill


class LearningDirection(models.Model):
	class Status(models.TextChoices):
		ACTIVE = 'ACTIVE', 'Active'
		COMPLETED = 'COMPLETED', 'Completed'
		CANCELLED = 'CANCELLED', 'Cancelled'

	partnership = models.ForeignKey(
		LearningPartnership,
		on_delete=models.CASCADE,
		related_name='learning_directions',
	)
	teacher = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='teaching_directions',
	)
	learner = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='learning_directions',
	)
	skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='learning_directions')
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('created_at', 'pk')
		constraints = [
			models.UniqueConstraint(
				fields=('partnership', 'teacher', 'learner', 'skill'),
				name='learning_direction_pair_skill_uniq',
			),
			models.CheckConstraint(condition=~models.Q(teacher=models.F('learner')), name='learning_direction_students_distinct'),
		]

	def clean(self):
		super().clean()
		if not self.partnership_id or not self.teacher_id or not self.learner_id or not self.skill_id:
			return

		partnership = self.partnership
		participant_ids = {partnership.student_one_id, partnership.student_two_id}
		if self.teacher_id not in participant_ids or self.learner_id not in participant_ids:
			raise ValidationError('Teacher and learner must belong to this partnership.')
		if self.teacher_id == self.learner_id:
			raise ValidationError('A student cannot teach themselves.')

		matched_skills = partnership.match.matched_skills
		if self.teacher_id == partnership.student_one_id:
			direction_key = 'student_two_learns_from_one'
		else:
			direction_key = 'student_one_learns_from_two'
		allowed_skill_ids = {
			item['skill_id'] for item in matched_skills.get(direction_key, [])
		}
		if self.skill_id not in allowed_skill_ids:
			raise ValidationError('This skill direction is not part of the accepted match.')

		if not OfferedSkill.objects.filter(
			profile_id=self.teacher_id,
			skill_id=self.skill_id,
			skill__is_active=True,
		).exists():
			raise ValidationError('The teacher must currently offer this skill.')
		if not LearningSkill.objects.filter(
			profile_id=self.learner_id,
			skill_id=self.skill_id,
			skill__is_active=True,
		).exists():
			raise ValidationError('The learner must currently want to learn this skill.')

	def __str__(self):
		return f'{self.teacher} teaches {self.learner} {self.skill}'


class LearningPlan(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'DRAFT', 'Draft'
		ACTIVE = 'ACTIVE', 'Active'
		COMPLETED = 'COMPLETED', 'Completed'
		CANCELLED = 'CANCELLED', 'Cancelled'

	learning_direction = models.ForeignKey(
		LearningDirection,
		on_delete=models.CASCADE,
		related_name='learning_plans',
	)
	title = models.CharField(max_length=160)
	description = models.TextField(blank=True)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_learning_plans',
	)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('created_at', 'pk')

	def clean(self):
		super().clean()
		if self.learning_direction_id and self.created_by_id:
			if self.learning_direction.teacher.user_id != self.created_by_id:
				raise ValidationError('Only the direction teacher can create this learning plan.')

	@property
	def total_lessons(self):
		return self.lessons.count()

	@property
	def completed_lessons(self):
		return sum(lesson.is_completed for lesson in self.lessons.all())

	@property
	def progress_percentage(self):
		total = self.total_lessons
		if not total:
			return 0
		return round(self.completed_lessons * 100 / total, 1)

	def __str__(self):
		return self.title


class Lesson(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
		COMPLETED = 'COMPLETED', 'Completed'

	learning_plan = models.ForeignKey(
		LearningPlan,
		on_delete=models.CASCADE,
		related_name='lessons',
	)
	title = models.CharField(max_length=160)
	description = models.TextField(blank=True)
	order = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
	estimated_duration = models.PositiveSmallIntegerField(
		null=True,
		blank=True,
		validators=[MinValueValidator(1)],
		help_text='Estimated duration in minutes.',
	)
	status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('order', 'pk')
		constraints = [
			models.UniqueConstraint(fields=('learning_plan', 'order'), name='lesson_plan_order_uniq'),
		]

	def clean(self):
		super().clean()
		if self.order is not None and self.order < 1:
			raise ValidationError({'order': 'Lesson order must be at least 1.'})

	def __str__(self):
		return f'{self.learning_plan}: {self.order}. {self.title}'

	@property
	def is_completed(self):
		learner_id = self.learning_plan.learning_direction.learner_id
		assignments = [
			assignment for assignment in self.assignments.all()
			if assignment.status == Assignment.Status.ACTIVE
		]
		return bool(assignments) and all(
			any(
				submission.learner_id == learner_id
				and submission.status in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED)
				for submission in assignment.submissions.all()
			)
			for assignment in assignments
		)

	@property
	def progress_status(self):
		if self.is_completed:
			return self.Status.COMPLETED
		learner_id = self.learning_plan.learning_direction.learner_id
		if LearningMaterialAccess.objects.filter(
			learner_id=learner_id,
			material__lesson=self,
		).exists() or self.assignments.filter(
			status=Assignment.Status.ACTIVE,
			submissions__learner_id=learner_id,
		).exists():
			return self.Status.IN_PROGRESS
		return self.Status.PENDING


def validate_learning_material_size(upload):
	if upload.size > 20 * 1024 * 1024:
		raise ValidationError('Learning material files must be 20 MB or smaller.')


def validate_submission_file_size(upload):
	if upload.size > 20 * 1024 * 1024:
		raise ValidationError('Submission files must be 20 MB or smaller.')


def validate_assignment_resource_size(upload):
	if upload.size > 20 * 1024 * 1024:
		raise ValidationError('Assignment resource files must be 20 MB or smaller.')


class LearningMaterial(models.Model):
	class MaterialType(models.TextChoices):
		LINK = 'LINK', 'External Link'
		FILE = 'FILE', 'Uploaded File'

	lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='materials')
	title = models.CharField(max_length=160)
	description = models.TextField(blank=True)
	material_type = models.CharField(max_length=4, choices=MaterialType.choices)
	external_url = models.URLField(blank=True)
	file = models.FileField(
		upload_to='learning_materials/%Y/%m/',
		blank=True,
		validators=[
			FileExtensionValidator(
				allowed_extensions=['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'zip'],
			),
			validate_learning_material_size,
		],
	)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_learning_materials',
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('created_at', 'pk')

	def clean(self):
		super().clean()
		errors = {}
		if self.lesson_id and self.created_by_id:
			teacher_user_id = self.lesson.learning_plan.learning_direction.teacher.user_id
			if self.created_by_id != teacher_user_id:
				errors['created_by'] = 'Only the lesson teacher can add learning materials.'

		if self.material_type == self.MaterialType.LINK:
			if not self.external_url:
				errors['external_url'] = 'Enter a URL for an external link.'
			if self.file:
				errors['file'] = 'External links cannot include an uploaded file.'
		elif self.material_type == self.MaterialType.FILE:
			if not self.file:
				errors['file'] = 'Choose a file to upload.'
			if self.external_url:
				errors['external_url'] = 'Uploaded files cannot include an external URL.'

		if errors:
			raise ValidationError(errors)

	def __str__(self):
		return self.title


class LearningMaterialAccess(models.Model):
	material = models.ForeignKey(
		LearningMaterial,
		on_delete=models.CASCADE,
		related_name='learner_accesses',
	)
	learner = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='learning_material_accesses',
	)
	accessed_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=('material', 'learner'), name='learning_material_access_unique'),
		]

	def clean(self):
		super().clean()
		if self.material_id and self.learner_id:
			assigned_learner_id = self.material.lesson.learning_plan.learning_direction.learner_id
			if self.learner_id != assigned_learner_id:
				raise ValidationError({'learner': 'Only the assigned learner can record material access.'})


class Assignment(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'DRAFT', 'Draft'
		ACTIVE = 'ACTIVE', 'Active'
		CLOSED = 'CLOSED', 'Closed'

	lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='assignments')
	title = models.CharField(max_length=160)
	instructions = models.TextField()
	due_date = models.DateTimeField(null=True, blank=True)
	resource_file = models.FileField(
		upload_to='assignment_resources/%Y/%m/',
		blank=True,
		validators=[
			FileExtensionValidator(
				allowed_extensions=['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'zip'],
			),
			validate_assignment_resource_size,
		],
	)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_assignments',
	)
	status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('created_at', 'pk')

	def clean(self):
		super().clean()
		if self.lesson_id and self.created_by_id:
			teacher_id = self.lesson.learning_plan.learning_direction.teacher.user_id
			if self.created_by_id != teacher_id:
				raise ValidationError({'created_by': 'Only the lesson teacher can create this assignment.'})

	def __str__(self):
		return self.title


class LearningSession(models.Model):
	class Status(models.TextChoices):
		SCHEDULED = 'SCHEDULED', 'Scheduled'
		COMPLETED = 'COMPLETED', 'Completed'
		CANCELLED = 'CANCELLED', 'Cancelled'

	learning_direction = models.ForeignKey(
		LearningDirection,
		on_delete=models.CASCADE,
		related_name='sessions',
	)
	lesson = models.ForeignKey(
		Lesson,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='sessions',
	)
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	scheduled_start = models.DateTimeField()
	scheduled_end = models.DateTimeField()
	meeting_url = models.URLField(blank=True)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_learning_sessions',
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('scheduled_start', 'pk')

	def clean(self):
		super().clean()
		if self.title and not self.title.strip():
			raise ValidationError({'title': 'Session title is required.'})
		if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
			raise ValidationError({'scheduled_end': 'Session end time must be after the start time.'})
		if self.lesson_id and self.learning_direction_id:
			if self.lesson.learning_plan.learning_direction_id != self.learning_direction_id:
				raise ValidationError({'lesson': 'Choose a lesson from this learning direction.'})
		if self.created_by_id and self.learning_direction_id:
			if self.learning_direction.teacher.user_id != self.created_by_id:
				raise ValidationError({'created_by': 'Only the direction teacher can create this session.'})
		if self.status == self.Status.SCHEDULED and self.learning_direction_id and self.scheduled_start and self.scheduled_end:
			conflicts = LearningSession.objects.filter(
				learning_direction_id=self.learning_direction_id,
				status=self.Status.SCHEDULED,
			).exclude(pk=self.pk)
			for other in conflicts:
				if self.scheduled_start < other.scheduled_end and self.scheduled_end > other.scheduled_start:
					raise ValidationError('This session overlaps with an existing scheduled session for this learning direction.')

	@property
	def is_live(self):
		now = timezone.now()
		return (
			self.status == self.Status.SCHEDULED
			and self.scheduled_start <= now < self.scheduled_end
		)

	def __str__(self):
		return self.title


class Submission(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'DRAFT', 'Draft'
		SUBMITTED = 'SUBMITTED', 'Submitted'
		EVALUATED = 'EVALUATED', 'Evaluated'

	assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions')
	learner = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='assignment_submissions',
	)
	answer_text = models.TextField(blank=True)
	file = models.FileField(
		upload_to='assignment_submissions/%Y/%m/',
		blank=True,
		validators=[
			FileExtensionValidator(
				allowed_extensions=['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'zip'],
			),
			validate_submission_file_size,
		],
	)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
	submitted_at = models.DateTimeField(null=True, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('-updated_at', 'pk')
		constraints = [
			models.UniqueConstraint(fields=('assignment', 'learner'), name='assignment_learner_submission_uniq'),
		]

	def clean(self):
		super().clean()
		if self.assignment_id and self.learner_id:
			direction = self.assignment.lesson.learning_plan.learning_direction
			if direction.learner_id != self.learner_id:
				raise ValidationError({'learner': 'Only the assigned learner can submit this assignment.'})
		if not (self.answer_text or '').strip() and not self.file:
			raise ValidationError('Add a written answer, attach a file, or provide both.')
		if self.status == self.Status.SUBMITTED and self.submitted_at is None:
			raise ValidationError({'status': 'Submitted work must include a submission timestamp.'})
		if self.status == self.Status.EVALUATED and self.submitted_at is None:
			raise ValidationError({'status': 'A submission must be submitted before it can be marked as evaluated.'})

	def __str__(self):
		return f'{self.assignment} - {self.learner} ({self.get_status_display()})'


class Evaluation(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		EVALUATED = 'EVALUATED', 'Evaluated'

	submission = models.OneToOneField(Submission, on_delete=models.CASCADE, related_name='evaluation')
	evaluator = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='created_evaluations',
	)
	feedback = models.TextField(blank=True)
	score = models.DecimalField(
		max_digits=5,
		decimal_places=2,
		null=True,
		blank=True,
		validators=[MinValueValidator(0), MaxValueValidator(100)],
	)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('-updated_at', 'pk')

	def clean(self):
		super().clean()
		if not self.submission_id or not self.evaluator_id:
			return
		direction = self.submission.assignment.lesson.learning_plan.learning_direction
		if direction.teacher.user_id != self.evaluator_id:
			raise ValidationError({'evaluator': 'Only the learning direction teacher can evaluate this submission.'})
		if self.status == self.Status.EVALUATED:
			if self.submission.status not in (Submission.Status.SUBMITTED, Submission.Status.EVALUATED):
				raise ValidationError('Only a submitted assignment can be evaluated.')
			if self.score is None and not self.feedback.strip():
				raise ValidationError('Add feedback or a score before completing the evaluation.')

	def __str__(self):
		return f'Evaluation for {self.submission}'


class Review(models.Model):
	learning_direction = models.ForeignKey(
		LearningDirection,
		on_delete=models.CASCADE,
		related_name='reviews',
	)
	reviewer = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='written_reviews',
	)
	reviewee = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='received_reviews',
	)
	rating = models.PositiveSmallIntegerField(
		validators=[MinValueValidator(1), MaxValueValidator(5)],
	)
	comment = models.CharField(max_length=1000, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('-created_at', 'pk')
		constraints = [
			models.UniqueConstraint(
				fields=('learning_direction', 'reviewer'),
				name='review_direction_reviewer_uniq',
			),
			models.CheckConstraint(
				condition=models.Q(rating__gte=1, rating__lte=5),
				name='review_rating_1_to_5',
			),
		]

	def clean(self):
		super().clean()
		if not self.learning_direction_id:
			return

		direction = self.learning_direction
		if self.reviewer_id and self.reviewer_id != direction.learner_id:
			raise ValidationError({'reviewer': 'Only the learning direction learner can submit a review.'})
		if self.reviewee_id and self.reviewee_id != direction.teacher_id:
			raise ValidationError({'reviewee': 'A review must be about the learning direction teacher.'})
		if not direction.sessions.filter(status=LearningSession.Status.COMPLETED).exists():
			raise ValidationError('A review is available only after a completed learning session.')

	def __str__(self):
		return f'{self.reviewer} reviewed {self.reviewee} ({self.rating}/5)'
