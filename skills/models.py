from django.db import models
from django.db.models.functions import Lower


class Skill(models.Model):
	class Category(models.TextChoices):
		PROGRAMMING = 'PROGRAMMING', 'Programming'
		WEB_DEVELOPMENT = 'WEB_DEVELOPMENT', 'Web Development'
		DATABASE = 'DATABASE', 'Database'
		DESIGN = 'DESIGN', 'Design'
		OFFICE_TOOLS = 'OFFICE_TOOLS', 'Office Tools'
		COMMUNICATION = 'COMMUNICATION', 'Communication'
		MUSIC = 'MUSIC', 'Music'
		PHOTOGRAPHY = 'PHOTOGRAPHY', 'Photography'
		VIDEO_EDITING = 'VIDEO_EDITING', 'Video Editing'
		OTHER = 'OTHER', 'Other'

	name = models.CharField(max_length=100)
	category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
	description = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('name',)
		constraints = [
			models.UniqueConstraint(Lower('name'), name='skill_name_ci_uniq'),
		]

	def clean(self):
		super().clean()
		self.name = ' '.join(self.name.split())

	def __str__(self):
		return self.name


class OfferedSkill(models.Model):
	class Proficiency(models.TextChoices):
		BEGINNER = 'BEGINNER', 'Beginner'
		INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
		ADVANCED = 'ADVANCED', 'Advanced'
		EXPERT = 'EXPERT', 'Expert'

	profile = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='offered_skills',
	)
	skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='offerings')
	proficiency = models.CharField(max_length=12, choices=Proficiency.choices)
	description = models.CharField(max_length=500, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('created_at',)
		constraints = [
			models.UniqueConstraint(fields=('profile', 'skill'), name='offered_profile_skill_uniq'),
		]

	def __str__(self):
		return f'{self.profile} teaches {self.skill}'


class LearningSkill(models.Model):
	class LearningLevel(models.TextChoices):
		BEGINNER = 'BEGINNER', 'Beginner'
		INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
		ADVANCED = 'ADVANCED', 'Advanced'

	profile = models.ForeignKey(
		'profiles.StudentProfile',
		on_delete=models.CASCADE,
		related_name='learning_skills',
	)
	skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='learners')
	learning_level = models.CharField(max_length=12, choices=LearningLevel.choices)
	goal = models.CharField(max_length=500, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('created_at',)
		constraints = [
			models.UniqueConstraint(fields=('profile', 'skill'), name='learning_profile_skill_uniq'),
		]

	def __str__(self):
		return f'{self.profile} wants to learn {self.skill}'
