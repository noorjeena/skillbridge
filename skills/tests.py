from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from profiles.models import StudentProfile

from .models import LearningSkill, OfferedSkill, Skill

User = get_user_model()


class SkillManagementTests(TestCase):
	def setUp(self):
		self.student = User.objects.create_user(
			username='student-one',
			password='Strong-pass-2026!',
		)
		self.profile = StudentProfile.objects.get(user=self.student)
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		self.django, _ = Skill.objects.get_or_create(
			name='Django',
			defaults={'category': Skill.Category.WEB_DEVELOPMENT},
		)
		self.client.force_login(self.student)

	def test_student_can_create_offered_skill(self):
		response = self.client.post(reverse('skills:teach-add'), {
			'skill': self.python.pk,
			'proficiency': OfferedSkill.Proficiency.ADVANCED,
			'description': 'Comfortable teaching Python fundamentals.',
		})

		self.assertRedirects(response, reverse('skills:index'))
		offered = OfferedSkill.objects.get(profile=self.profile, skill=self.python)
		self.assertEqual(offered.proficiency, OfferedSkill.Proficiency.ADVANCED)

	def test_student_can_create_learning_skill(self):
		response = self.client.post(reverse('skills:learn-add'), {
			'skill': self.django.pk,
			'learning_level': LearningSkill.LearningLevel.BEGINNER,
			'goal': 'Build a small Django website.',
		})

		self.assertRedirects(response, reverse('skills:index'))
		learning = LearningSkill.objects.get(profile=self.profile, skill=self.django)
		self.assertEqual(learning.learning_level, LearningSkill.LearningLevel.BEGINNER)

	def test_skills_page_renders_premium_skill_sections_and_setup_actions(self):
		response = self.client.get(reverse('skills:index'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/skills.css?v=20261005-1')
		self.assertContains(response, 'Build your skill exchange')
		self.assertContains(response, 'Skills you can teach')
		self.assertContains(response, 'Skills you want to learn')
		self.assertContains(response, f'href="{reverse("skills:teach-add")}"')
		self.assertContains(response, f'href="{reverse("skills:learn-add")}"')

	def test_both_skill_forms_offer_category_grouped_catalogue_selects(self):
		for url_name in ('skills:teach-add', 'skills:learn-add'):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(url_name))

				self.assertEqual(response.status_code, 200)
				self.assertContains(response, '<select', html=False)
				self.assertContains(response, 'optgroup label="Programming"', html=False)
				self.assertContains(response, 'Python')
				self.assertContains(response, 'Django')
				self.assertNotContains(response, 'name="skill" type="text"', html=False)
				self.assertContains(response, 'Select one of', html=False)

	def test_student_can_edit_and_delete_own_learning_skill(self):
		learning = LearningSkill.objects.create(
			profile=self.profile,
			skill=self.django,
			learning_level='BEGINNER',
		)

		edit_response = self.client.post(reverse('skills:learn-edit', args=(learning.pk,)), {
			'skill': self.django.pk,
			'learning_level': 'ADVANCED',
			'goal': 'Build a full project.',
		})
		learning.refresh_from_db()
		self.assertRedirects(edit_response, reverse('skills:index'))
		self.assertEqual(learning.learning_level, 'ADVANCED')

		delete_response = self.client.post(reverse('skills:learn-delete', args=(learning.pk,)))

		self.assertRedirects(delete_response, reverse('skills:index'))
		self.assertFalse(LearningSkill.objects.filter(pk=learning.pk).exists())

	def test_duplicate_offered_skill_is_rejected(self):
		OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='ADVANCED')

		response = self.client.post(reverse('skills:teach-add'), {
			'skill': self.python.pk,
			'proficiency': 'INTERMEDIATE',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(OfferedSkill.objects.filter(profile=self.profile, skill=self.python).count(), 1)
		self.assertContains(response, 'already in this list')

	def test_duplicate_learning_skill_is_rejected(self):
		LearningSkill.objects.create(profile=self.profile, skill=self.django, learning_level='BEGINNER')

		response = self.client.post(reverse('skills:learn-add'), {
			'skill': self.django.pk,
			'learning_level': 'ADVANCED',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(LearningSkill.objects.filter(profile=self.profile, skill=self.django).count(), 1)
		self.assertContains(response, 'already in this list')

	def test_student_can_edit_own_offered_skill(self):
		offered = OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='BEGINNER')

		response = self.client.post(reverse('skills:teach-edit', args=(offered.pk,)), {
			'skill': self.python.pk,
			'proficiency': 'EXPERT',
			'description': 'Can teach advanced topics.',
		})

		self.assertRedirects(response, reverse('skills:index'))
		offered.refresh_from_db()
		self.assertEqual(offered.proficiency, 'EXPERT')

	def test_student_can_delete_own_offered_skill(self):
		offered = OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='ADVANCED')

		response = self.client.post(reverse('skills:teach-delete', args=(offered.pk,)))

		self.assertRedirects(response, reverse('skills:index'))
		self.assertFalse(OfferedSkill.objects.filter(pk=offered.pk).exists())

	def test_student_cannot_edit_another_students_offered_skill(self):
		other_student = User.objects.create_user(username='student-two', password='Strong-pass-2026!')
		other_offered = OfferedSkill.objects.create(
			profile=other_student.student_profile,
			skill=self.python,
			proficiency='INTERMEDIATE',
		)

		response = self.client.post(reverse('skills:teach-edit', args=(other_offered.pk,)), {
			'skill': self.python.pk,
			'proficiency': 'EXPERT',
		})

		self.assertEqual(response.status_code, 404)
		other_offered.refresh_from_db()
		self.assertEqual(other_offered.proficiency, 'INTERMEDIATE')

	def test_student_cannot_delete_another_students_offered_skill(self):
		other_student = User.objects.create_user(username='student-two', password='Strong-pass-2026!')
		other_offered = OfferedSkill.objects.create(
			profile=other_student.student_profile,
			skill=self.python,
			proficiency='INTERMEDIATE',
		)

		response = self.client.post(reverse('skills:teach-delete', args=(other_offered.pk,)))

		self.assertEqual(response.status_code, 404)
		self.assertTrue(OfferedSkill.objects.filter(pk=other_offered.pk).exists())

	def test_inactive_skill_cannot_be_selected(self):
		inactive_skill = Skill.objects.create(name='Legacy Tool', is_active=False)

		response = self.client.post(reverse('skills:teach-add'), {
			'skill': inactive_skill.pk,
			'proficiency': 'BEGINNER',
		})

		self.assertEqual(response.status_code, 200)
		self.assertFalse(OfferedSkill.objects.filter(profile=self.profile, skill=inactive_skill).exists())
		available_skills = response.context['form'].fields['skill'].queryset
		self.assertIn(self.django, available_skills)
		self.assertIn(self.python, available_skills)
		self.assertNotIn(inactive_skill, available_skills)

	def test_admin_can_create_skill_catalogue_entries(self):
		admin_user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)

		response = self.client.post(reverse('admin:skills_skill_add'), {
			'name': 'Figma',
			'category': Skill.Category.DESIGN,
			'description': 'Interface design tool.',
			'is_active': 'on',
			'_save': 'Save',
		}, follow=True)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(Skill.objects.filter(name='Figma', is_active=True).exists())

	def test_unauthenticated_users_cannot_access_skill_pages(self):
		self.client.logout()
		protected_paths = (
			reverse('skills:index'),
			reverse('skills:teach-add'),
			reverse('skills:learn-add'),
		)

		for path in protected_paths:
			with self.subTest(path=path):
				response = self.client.get(path)
				self.assertEqual(response.status_code, 302)
				self.assertIn(reverse('login'), response.url)

	def test_skill_lists_display_on_student_profile(self):
		OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.profile, skill=self.django, learning_level='BEGINNER')

		response = self.client.get(reverse('profile-detail'))

		self.assertContains(response, 'Skills I Can Teach')
		self.assertContains(response, 'Python')
		self.assertContains(response, 'Advanced')
		self.assertContains(response, 'Skills I Want To Learn')
		self.assertContains(response, 'Django')
		self.assertContains(response, 'Beginner')

	def test_same_skill_can_be_offered_and_learned(self):
		OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='INTERMEDIATE')
		LearningSkill.objects.create(profile=self.profile, skill=self.python, learning_level='ADVANCED')

		self.assertTrue(OfferedSkill.objects.filter(profile=self.profile, skill=self.python).exists())
		self.assertTrue(LearningSkill.objects.filter(profile=self.profile, skill=self.python).exists())

	def test_database_constraints_prevent_duplicates_in_each_list(self):
		OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='BEGINNER')
		LearningSkill.objects.create(profile=self.profile, skill=self.python, learning_level='BEGINNER')

		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				OfferedSkill.objects.create(profile=self.profile, skill=self.python, proficiency='EXPERT')
		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				LearningSkill.objects.create(profile=self.profile, skill=self.python, learning_level='ADVANCED')

	def test_skill_names_are_case_insensitively_unique(self):
		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				Skill.objects.create(name='python', category=Skill.Category.PROGRAMMING)
