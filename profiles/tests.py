from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import StudentProfile

User = get_user_model()


class StudentProfileTests(TestCase):
	def setUp(self):
		self.student = User.objects.create_user(
			username='student-one',
			password='Strong-pass-2026!',
		)
		self.profile = StudentProfile.objects.get(user=self.student)

	def test_student_creation_creates_one_empty_profile(self):
		self.assertEqual(StudentProfile.objects.filter(user=self.student).count(), 1)
		self.assertEqual(self.profile.full_name, '')
		self.assertEqual(self.profile.display_name, 'student-one')
		self.assertEqual(self.profile.completion_percentage, 20)

	def test_profile_uses_account_name_before_username_and_can_be_edited(self):
		self.student.first_name = 'Anandhu'
		self.student.last_name = 'Student'
		self.student.save(update_fields=('first_name', 'last_name'))
		self.client.force_login(self.student)

		profile_response = self.client.get(reverse('profile-detail'))
		edit_response = self.client.get(reverse('profile-edit'))

		self.assertContains(profile_response, 'Anandhu Student')
		self.assertEqual(edit_response.status_code, 200)
		self.assertContains(edit_response, 'name="full_name"')
		self.assertContains(edit_response, 'value="Anandhu Student"')

		save_response = self.client.post(reverse('profile-edit'), {
			'full_name': 'Anandhu S.',
			'department': '',
			'academic_year': '',
			'bio': '',
		})

		self.assertRedirects(save_response, reverse('profile-detail'))
		self.profile.refresh_from_db()
		self.assertEqual(self.profile.full_name, 'Anandhu S.')
		self.assertEqual(self.profile.display_name, 'Anandhu S.')

	def test_registration_creates_an_empty_profile(self):
		response = self.client.post(reverse('register'), {
			'username': 'registered-student',
			'email': 'registered@example.com',
			'password1': 'Strong-pass-2026!',
			'password2': 'Strong-pass-2026!',
		})

		self.assertRedirects(response, reverse('login'))
		registered_student = User.objects.get(username='registered-student')
		self.assertEqual(StudentProfile.objects.filter(user=registered_student).count(), 1)
		self.assertEqual(registered_student.student_profile.full_name, '')

	def test_authenticated_student_can_view_profile(self):
		self.client.force_login(self.student)

		response = self.client.get(reverse('profile-detail'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/profile.css?v=20261005-2')
		self.assertContains(response, 'YOUR LEARNING IDENTITY')
		self.assertContains(response, 'Skills I can teach')
		self.assertContains(response, 'Skills I want to learn')
		self.assertContains(response, 'Profile completion')
		self.assertContains(response, 'student-one')
		self.assertContains(response, '20%')
		self.assertContains(response, reverse('profile-edit'))
		self.assertContains(response, 'student-profile-hero')
		self.assertContains(response, 'Edit profile')
		self.assertContains(response, 'student-profile-photo-fallback')

	def test_profile_edit_page_shows_photo_preview(self):
		self.client.force_login(self.student)

		response = self.client.get(reverse('profile-edit'))

		self.assertContains(response, 'id="profile-photo-preview"')
		self.assertContains(response, 'id="id_profile_photo"')

	def test_authenticated_student_can_edit_own_profile(self):
		self.client.force_login(self.student)

		response = self.client.post(reverse('profile-edit'), {
			'full_name': 'Anandhu Student',
			'department': 'Computer Applications',
			'academic_year': 'MCA Year 1',
			'bio': 'I enjoy collaborative learning.',
		})

		self.assertRedirects(response, reverse('profile-detail'))
		self.profile.refresh_from_db()
		self.assertEqual(self.profile.full_name, 'Anandhu Student')
		self.assertEqual(self.profile.department, 'Computer Applications')
		self.assertEqual(self.profile.academic_year, 'MCA Year 1')

	def test_student_cannot_view_or_edit_another_students_profile(self):
		other_student = User.objects.create_user(
			username='student-two',
			password='Strong-pass-2026!',
		)
		other_profile = other_student.student_profile
		other_profile.full_name = 'Private Student'
		other_profile.save()
		self.client.force_login(self.student)

		detail_response = self.client.get(reverse('profile-detail'))
		edit_response = self.client.post(reverse('profile-edit'), {
			'full_name': 'Changed by another student',
			'department': 'Other department',
			'academic_year': 'MCA Year 2',
			'bio': 'Not the owner.',
		})
		guessed_id_response = self.client.post(f'/profile/{other_profile.pk}/edit/', {
			'full_name': 'Changed by another student',
		})

		self.assertNotContains(detail_response, 'Private Student')
		self.assertRedirects(edit_response, reverse('profile-detail'))
		self.assertEqual(guessed_id_response.status_code, 404)
		other_profile.refresh_from_db()
		self.assertEqual(other_profile.full_name, 'Private Student')

	def test_unauthenticated_users_are_redirected_from_profile_pages(self):
		for url_name in ('profile-detail', 'profile-edit'):
			response = self.client.get(reverse(url_name))
			self.assertRedirects(
				response,
				f'{reverse("login")}?next={reverse(url_name)}',
			)

	def test_student_can_upload_a_valid_profile_photo(self):
		image_bytes = BytesIO()
		Image.new('RGB', (2, 2), color='white').save(image_bytes, format='PNG')
		upload = SimpleUploadedFile(
			'portrait.png',
			image_bytes.getvalue(),
			content_type='image/png',
		)

		with TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				self.client.force_login(self.student)
				response = self.client.post(reverse('profile-edit'), {
					'full_name': 'Anandhu Student',
					'department': 'Computer Applications',
					'academic_year': 'MCA Year 1',
					'bio': 'I enjoy collaborative learning.',
					'profile_photo': upload,
				})

				self.assertRedirects(response, reverse('profile-detail'))
				self.profile.refresh_from_db()
				self.assertTrue(self.profile.profile_photo.name)
				self.assertTrue(Path(media_root, self.profile.profile_photo.name).is_file())
				profile_response = self.client.get(reverse('profile-detail'))
				dashboard_response = self.client.get(reverse('home'))
				self.assertContains(profile_response, self.profile.profile_photo.url)
				self.assertContains(dashboard_response, self.profile.profile_photo.url)
				self.assertContains(dashboard_response, 'avatar-photo')

	def test_non_image_upload_is_rejected(self):
		upload = SimpleUploadedFile(
			'not-an-image.png',
			b'this is not an image',
			content_type='image/png',
		)
		self.client.force_login(self.student)

		response = self.client.post(reverse('profile-edit'), {
			'full_name': 'Anandhu Student',
			'profile_photo': upload,
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn(
			'Upload a valid image.',
			response.context['form'].errors['profile_photo'][0],
		)
