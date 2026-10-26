from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models


def validate_profile_photo_size(image):
	if image.size > 5 * 1024 * 1024:
		raise ValidationError('Profile photos must be 5 MB or smaller.')


class StudentProfile(models.Model):
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name='student_profile',
	)
	full_name = models.CharField(max_length=120, blank=True)
	profile_photo = models.ImageField(
		upload_to='profile_photos/',
		blank=True,
		validators=[
			FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp']),
			validate_profile_photo_size,
		],
	)
	department = models.CharField(max_length=120, blank=True)
	academic_year = models.CharField(max_length=40, blank=True)
	bio = models.CharField(max_length=500, blank=True)

	@property
	def display_name(self):
		return self.full_name.strip() or self.user.get_full_name().strip() or self.user.username

	@property
	def completion_percentage(self):
		values = (self.display_name, self.profile_photo, self.department, self.academic_year, self.bio)
		return round(sum(bool(value) for value in values) * 100 / len(values))

	@property
	def is_complete(self):
		return self.completion_percentage == 100

	@property
	def review_count(self):
		return self.received_reviews.count()

	@property
	def average_rating(self):
		from django.db.models import Avg

		return self.received_reviews.aggregate(average=Avg('rating'))['average']

	def __str__(self):
		return self.full_name or f'{self.user.username} profile'
