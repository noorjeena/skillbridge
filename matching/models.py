from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Match(models.Model):
	class MatchType(models.TextChoices):
		DIRECT_EXCHANGE = 'DIRECT_EXCHANGE', 'Direct Exchange'
		ONE_WAY_LEARNING = 'ONE_WAY_LEARNING', 'One-way Learning'

	class Status(models.TextChoices):
		SUGGESTED = 'SUGGESTED', 'Suggested'
		REQUESTED = 'REQUESTED', 'Requested'
		ACCEPTED = 'ACCEPTED', 'Accepted'
		REJECTED = 'REJECTED', 'Rejected'
		CANCELLED = 'CANCELLED', 'Cancelled'

	student_one = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='matches_as_one',
	)
	student_two = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='matches_as_two',
	)
	compatibility_score = models.PositiveSmallIntegerField(
		validators=[MinValueValidator(0), MaxValueValidator(100)],
	)
	match_type = models.CharField(max_length=20, choices=MatchType.choices)
	matched_skills = models.JSONField(default=dict)
	score_breakdown = models.JSONField(default=dict)
	status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUGGESTED)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('-compatibility_score', 'created_at')
		constraints = [
			models.UniqueConstraint(
				fields=('student_one', 'student_two'),
				name='match_pair_uniq',
			),
			models.CheckConstraint(
				condition=Q(student_one__lt=F('student_two')),
				name='match_pair_canonical_order',
			),
			models.CheckConstraint(
				condition=Q(compatibility_score__lte=100),
				name='match_score_lte_100',
			),
		]

	def __str__(self):
		return f'{self.student_one} - {self.student_two} ({self.compatibility_score}%)'


class MatchRequest(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		ACCEPTED = 'ACCEPTED', 'Accepted'
		REJECTED = 'REJECTED', 'Rejected'
		CANCELLED = 'CANCELLED', 'Cancelled'

	match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='requests')
	sender = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='sent_match_requests',
	)
	receiver = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='received_match_requests',
	)
	message = models.CharField(max_length=500, blank=True)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
	created_at = models.DateTimeField(auto_now_add=True)
	responded_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ('-created_at',)
		constraints = [
			models.UniqueConstraint(
				fields=('match',),
				condition=Q(status='PENDING'),
				name='one_pending_request_per_match',
			),
			models.CheckConstraint(
				condition=~Q(sender=F('receiver')),
				name='match_request_distinct_students',
			),
		]

	def clean(self):
		super().clean()
		if not self.match_id or not self.sender_id or not self.receiver_id:
			return
		pair_ids = {self.match.student_one_id, self.match.student_two_id}
		if self.sender_id not in pair_ids or self.receiver_id not in pair_ids:
			raise ValidationError('The sender and receiver must be the students in this match.')
		if self.sender_id == self.receiver_id:
			raise ValidationError('A student cannot send a match request to themselves.')

	def __str__(self):
		return f'{self.sender} -> {self.receiver} ({self.get_status_display()})'


class LearningPartnership(models.Model):
	class Status(models.TextChoices):
		ACTIVE = 'ACTIVE', 'Active'
		CANCELLED = 'CANCELLED', 'Cancelled'

	match = models.OneToOneField(Match, on_delete=models.PROTECT, related_name='partnership')
	student_one = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='partnerships_as_one',
	)
	student_two = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='partnerships_as_two',
	)
	relationship_type = models.CharField(max_length=20, choices=Match.MatchType.choices)
	primary_teacher = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.PROTECT,
		related_name='one_way_teaching_partnerships',
		null=True,
		blank=True,
	)
	primary_learner = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.PROTECT,
		related_name='one_way_learning_partnerships',
		null=True,
		blank=True,
	)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-created_at',)
		constraints = [
			models.UniqueConstraint(
				fields=('student_one', 'student_two'),
				condition=Q(status='ACTIVE'),
				name='active_partnership_pair_uniq',
			),
			models.CheckConstraint(
				condition=Q(student_one__lt=F('student_two')),
				name='partnership_pair_canonical_order',
			),
			models.CheckConstraint(
				condition=(
					Q(
						relationship_type=Match.MatchType.DIRECT_EXCHANGE,
						primary_teacher__isnull=True,
						primary_learner__isnull=True,
					)
					| Q(
						relationship_type=Match.MatchType.ONE_WAY_LEARNING,
						primary_teacher__isnull=False,
						primary_learner__isnull=False,
					)
				),
				name='partnership_roles_match_type',
			),
			models.CheckConstraint(
				condition=(Q(primary_teacher__isnull=True) | ~Q(primary_teacher=F('primary_learner'))),
				name='partnership_teacher_learner_distinct',
			),
		]

	def __str__(self):
		return f'{self.student_one} - {self.student_two} ({self.get_relationship_type_display()})'


class Conversation(models.Model):
	partnership = models.OneToOneField(
		LearningPartnership,
		on_delete=models.CASCADE,
		related_name='conversation',
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-created_at', 'pk')

	def __str__(self):
		return f'Conversation for {self.partnership}'

	@property
	def student_one(self):
		return self.partnership.student_one

	@property
	def student_two(self):
		return self.partnership.student_two

	def other_student_for(self, student_profile):
		if student_profile.pk == self.partnership.student_one_id:
		    return self.partnership.student_two
		if student_profile.pk == self.partnership.student_two_id:
		    return self.partnership.student_one
		raise ValueError('This student is not a participant in this conversation.')


class Message(models.Model):
	conversation = models.ForeignKey(
		Conversation,
		on_delete=models.CASCADE,
		related_name='messages',
	)
	sender = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		related_name='sent_messages',
	)
	content = models.TextField(max_length=2000)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	is_read = models.BooleanField(default=False)

	class Meta:
		ordering = ('created_at', 'pk')
		indexes = [
			models.Index(fields=('conversation', 'created_at')),
		]

	def clean(self):
		super().clean()
		if not self.content or not self.content.strip():
			raise ValidationError('Message content is required.')
		if len(self.content.strip()) > 2000:
			raise ValidationError('Messages must be 2000 characters or fewer.')
		if self.sender_id and self.conversation_id:
			participant_ids = {self.conversation.partnership.student_one_id, self.conversation.partnership.student_two_id}
			if self.sender.student_profile.pk not in participant_ids:
				raise ValidationError('Only partnership participants can send messages.')

	def __str__(self):
		return f'{self.sender} in {self.conversation}'
