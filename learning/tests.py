from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import Notification
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal

from matching.models import LearningPartnership, Match, MatchRequest
from matching.services import respond_to_match_request
from profiles.models import StudentProfile
from skills.models import LearningSkill, OfferedSkill, Skill

from .models import Assignment, Evaluation, LearningDirection, LearningMaterial, LearningMaterialAccess, LearningPlan, Lesson, LearningSession, Review, Submission
from .services import create_directions_for_partnership, create_review


User = get_user_model()


class LearningTests(TestCase):
	def setUp(self):
		self.student_a = User.objects.create_user(username='student-a', password='Strong-pass-2026!')
		self.student_b = User.objects.create_user(username='student-b', password='Strong-pass-2026!')
		self.student_c = User.objects.create_user(username='student-c', password='Strong-pass-2026!')
		self.profile_a = self.student_a.student_profile
		self.profile_b = self.student_b.student_profile
		self.profile_c = self.student_c.student_profile
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		self.excel = Skill.objects.create(name='Excel', category=Skill.Category.OFFICE_TOOLS)

	def create_direct_partnership(self, accept=False):
		OfferedSkill.objects.create(profile=self.profile_b, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.profile_a, skill=self.python, learning_level='BEGINNER')
		OfferedSkill.objects.create(profile=self.profile_a, skill=self.excel, proficiency='INTERMEDIATE')
		LearningSkill.objects.create(profile=self.profile_b, skill=self.excel, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.profile_a,
			student_two=self.profile_b,
			compatibility_score=100,
			match_type=Match.MatchType.DIRECT_EXCHANGE,
			status=Match.Status.REQUESTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [{'skill_id': self.excel.pk, 'skill': 'Excel'}],
			},
		)
		match_request = MatchRequest.objects.create(
			match=match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		if accept:
			respond_to_match_request(match_request, self.profile_b, accept=True)
			return match.partnership
		return match, match_request

	def create_one_way_partnership(self):
		OfferedSkill.objects.create(profile=self.profile_b, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.profile_a, skill=self.python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.profile_a,
			student_two=self.profile_b,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.profile_a,
			student_two=self.profile_b,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.profile_b,
			primary_learner=self.profile_a,
		)
		return partnership

	def create_plan(self, direction, *, status=LearningPlan.Status.ACTIVE):
		return LearningPlan.objects.create(
			learning_direction=direction,
			title='Python Beginner',
			description='Core Python concepts.',
			created_by=direction.teacher.user,
			status=status,
		)

	def test_learning_workspace_empty_state_has_premium_discovery_action(self):
		self.client.force_login(self.student_a)

		response = self.client.get(reverse('learning:directions'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/learning.css?v=20261005-5')
		self.assertContains(response, 'Your learning journey starts with a connection')
		self.assertContains(response, reverse('matching:index'))

	def test_direct_exchange_acceptance_creates_two_learning_directions(self):
		partnership = self.create_direct_partnership(accept=True)

		directions = list(partnership.learning_directions.select_related('teacher', 'learner', 'skill').order_by('skill__name'))

		self.assertEqual(len(directions), 2)
		self.assertEqual((directions[0].teacher, directions[0].learner, directions[0].skill), (self.profile_a, self.profile_b, self.excel))
		self.assertEqual((directions[1].teacher, directions[1].learner, directions[1].skill), (self.profile_b, self.profile_a, self.python))

	def test_one_way_acceptance_creates_exactly_one_learning_direction(self):
		match = Match.objects.create(
			student_one=self.profile_a,
			student_two=self.profile_b,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.profile_a,
			student_two=self.profile_b,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.profile_b,
			primary_learner=self.profile_a,
		)
		OfferedSkill.objects.create(profile=self.profile_b, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.profile_a, skill=self.python, learning_level='BEGINNER')

		directions = create_directions_for_partnership(partnership)

		self.assertEqual(len(directions), 1)
		self.assertEqual(directions[0].teacher, self.profile_b)
		self.assertEqual(directions[0].learner, self.profile_a)
		self.assertEqual(directions[0].skill, self.python)

	def test_direction_rejects_a_teacher_learner_skill_not_in_match(self):
		partnership = self.create_direct_partnership(accept=True)

		with self.assertRaises(ValidationError):
			LearningDirection(
				partnership=partnership,
				teacher=self.profile_b,
				learner=self.profile_a,
				skill=self.excel,
			).full_clean()

	def test_direction_database_constraint_prevents_duplicates(self):
		partnership = self.create_direct_partnership(accept=True)
		direction = partnership.learning_directions.first()

		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				LearningDirection.objects.create(
					partnership=partnership,
					teacher=direction.teacher,
					learner=direction.learner,
					skill=direction.skill,
				)

	def test_teacher_can_create_a_learning_plan(self):
		partnership = self.create_direct_partnership(accept=True)
		direction = partnership.learning_directions.get(skill=self.python)
		self.client.force_login(self.student_b)

		form_response = self.client.get(reverse('learning:plan-create'))
		self.assertEqual(form_response.status_code, 200)
		self.assertContains(form_response, 'learning-plan-form-card')
		self.assertContains(form_response, 'Create a learning plan')
		self.assertContains(form_response, 'learning-plan-submit-button')

		response = self.client.post(reverse('learning:plan-create'), {
			'learning_direction': direction.pk,
			'title': 'Python Beginner',
			'description': 'Core Python concepts.',
			'status': LearningPlan.Status.ACTIVE,
		})

		plan = LearningPlan.objects.get(title='Python Beginner')
		self.assertRedirects(response, reverse('learning:plan-detail', args=(plan.pk,)))
		self.assertEqual(plan.created_by, self.student_b)

	def test_non_teacher_cannot_create_or_edit_another_teachers_plan(self):
		partnership = self.create_direct_partnership(accept=True)
		python_direction = partnership.learning_directions.get(skill=self.python)
		plan = self.create_plan(python_direction)
		self.client.force_login(self.student_a)

		create_response = self.client.post(reverse('learning:plan-create'), {
			'learning_direction': python_direction.pk,
			'title': 'Unauthorized Plan',
			'status': LearningPlan.Status.ACTIVE,
		})
		edit_response = self.client.post(reverse('learning:plan-edit', args=(plan.pk,)), {
			'learning_direction': python_direction.pk,
			'title': 'Changed by learner',
			'status': LearningPlan.Status.ACTIVE,
		})

		self.assertEqual(create_response.status_code, 200)
		self.assertFalse(LearningPlan.objects.filter(title='Unauthorized Plan').exists())
		self.assertEqual(edit_response.status_code, 404)
		plan.refresh_from_db()
		self.assertEqual(plan.title, 'Python Beginner')

	def test_teacher_manage_plan_link_opens_detail_page(self):
		partnership = self.create_direct_partnership(accept=True)
		direction = partnership.learning_directions.get(skill=self.python)
		plan = self.create_plan(direction)
		self.client.force_login(self.student_b)

		response = self.client.get(reverse('learning:directions'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, f'href="{reverse("learning:plan-detail", args=(plan.pk,))}"')
		self.assertNotContains(response, f'href="{reverse("learning:plan-edit", args=(plan.pk,))}"')

	def test_plan_detail_exposes_teacher_actions_for_each_lesson_only_to_teacher(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		lesson = Lesson.objects.create(learning_plan=plan, title='Notes and exercises', order=1)
		self.client.force_login(self.student_b)

		teacher_response = self.client.get(reverse('learning:plan-detail', args=(plan.pk,)))

		self.assertContains(teacher_response, '/static/css/learning.css?v=20261005-5')
		self.assertContains(teacher_response, 'learning-plan-detail-hero')
		self.assertContains(teacher_response, 'learning-plan-progress-card')
		self.assertContains(teacher_response, 'Add / Edit Lesson Notes')
		self.assertContains(teacher_response, 'Upload PDF / Add Material')
		self.assertContains(teacher_response, 'Create Assignment')
		self.assertContains(teacher_response, reverse('learning:material-add', args=(lesson.pk,)))
		self.assertContains(teacher_response, reverse('learning:assignment-add', args=(lesson.pk,)))
		self.assertContains(teacher_response, reverse('learning:session-add', args=(plan.learning_direction_id,)))

		self.client.force_login(self.student_a)
		learner_response = self.client.get(reverse('learning:plan-detail', args=(plan.pk,)))

		self.assertContains(learner_response, lesson.title)
		self.assertNotContains(learner_response, 'Upload PDF / Add Material')
		self.assertNotContains(learner_response, 'Create Assignment')
		self.assertNotContains(learner_response, 'Schedule Session')

	def test_teacher_can_add_ordered_lessons(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		self.client.force_login(self.student_b)
		first_response = self.client.post(reverse('learning:lesson-add', args=(plan.pk,)), {
			'title': 'Introduction to Python',
			'description': 'Meet Python.',
			'order': 1,
			'estimated_duration': 30,
		})
		second_response = self.client.post(reverse('learning:lesson-add', args=(plan.pk,)), {
			'title': 'Variables and Data Types',
			'description': 'Work with values.',
			'order': 2,
			'estimated_duration': 60,
		})

		self.assertRedirects(first_response, reverse('learning:plan-detail', args=(plan.pk,)))
		self.assertRedirects(second_response, reverse('learning:plan-detail', args=(plan.pk,)))
		self.assertEqual(list(plan.lessons.values_list('order', flat=True)), [1, 2])

	def test_duplicate_lesson_order_is_rejected(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		Lesson.objects.create(learning_plan=plan, title='Lesson One', order=1)
		self.client.force_login(self.student_b)

		response = self.client.post(reverse('learning:lesson-add', args=(plan.pk,)), {
			'title': 'Duplicate Order',
			'order': 1,
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(plan.lessons.count(), 1)

	def test_learner_can_view_but_not_edit_teacher_lesson(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		lesson = Lesson.objects.create(learning_plan=plan, title='Variables', order=1)
		self.client.force_login(self.student_a)

		view_response = self.client.get(reverse('learning:lesson-detail', args=(lesson.pk,)))
		edit_response = self.client.post(reverse('learning:lesson-edit', args=(lesson.pk,)), {
			'title': 'Changed Content',
			'order': 1,
		})

		self.assertEqual(view_response.status_code, 200)
		self.assertContains(view_response, 'Variables')
		self.assertEqual(edit_response.status_code, 404)
		lesson.refresh_from_db()
		self.assertEqual(lesson.title, 'Variables')

	def test_lesson_completes_only_after_all_active_assignments_are_submitted(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		lesson = Lesson.objects.create(learning_plan=plan, title='Variables', order=1)
		assignments = [
			Assignment.objects.create(
				lesson=lesson,
				title=f'Exercise {number}',
				instructions='Complete the exercise.',
				created_by=self.student_b,
				status=Assignment.Status.ACTIVE,
			)
			for number in (1, 2)
		]
		self.client.force_login(self.student_a)

		started = self.client.post(reverse('learning:lesson-status', args=(lesson.pk,)), {'status': Lesson.Status.IN_PROGRESS})
		lesson.refresh_from_db()
		completed = self.client.post(reverse('learning:lesson-status', args=(lesson.pk,)), {'status': Lesson.Status.COMPLETED})
		lesson.refresh_from_db()

		self.assertRedirects(started, reverse('learning:lesson-detail', args=(lesson.pk,)))
		self.assertRedirects(completed, reverse('learning:lesson-detail', args=(lesson.pk,)))
		self.assertEqual(lesson.status, Lesson.Status.IN_PROGRESS)
		self.assertFalse(lesson.is_completed)

		for index, assignment in enumerate(assignments):
			self.client.post(
				reverse('learning:assignment-submit', args=(assignment.pk,)),
				{'action': 'submit', 'answer_text': 'My completed answer.'},
			)
			lesson.refresh_from_db()
			if index == 0:
				self.assertFalse(lesson.is_completed)

		self.assertTrue(lesson.is_completed)
		self.assertEqual(lesson.status, Lesson.Status.COMPLETED)

	def test_progress_counts_lessons_only_after_all_active_assignments_are_submitted(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		lessons = [
			Lesson.objects.create(learning_plan=plan, title=f'Lesson {number}', order=number)
			for number in range(1, 9)
		]
		assignments = []
		for number, lesson in enumerate(lessons, start=1):
			assignment = Assignment.objects.create(
				lesson=lesson,
				title=f'Exercise {number}',
				instructions='Complete the exercise.',
				created_by=self.student_b,
				status=Assignment.Status.ACTIVE,
			)
			assignments.append(assignment)
			if number <= 2:
				Submission.objects.create(
					assignment=assignment,
					learner=self.profile_a,
					answer_text='Submitted answer.',
					status=Submission.Status.SUBMITTED,
					submitted_at=timezone.now(),
				)
		self.assertEqual(plan.progress_percentage, 25)

		self.client.force_login(self.student_a)
		self.client.post(
			reverse('learning:assignment-submit', args=(assignments[2].pk,)),
			{'action': 'submit', 'answer_text': 'Third submitted answer.'},
		)

		plan.refresh_from_db()
		self.assertEqual(plan.completed_lessons, 3)
		self.assertEqual(plan.progress_percentage, 37.5)

	def test_completed_lesson_cannot_be_moved_back(self):
		partnership = self.create_direct_partnership(accept=True)
		plan = self.create_plan(partnership.learning_directions.get(skill=self.python))
		lesson = Lesson.objects.create(learning_plan=plan, title='Done', order=1)
		assignment = Assignment.objects.create(
			lesson=lesson,
			title='Done assignment',
			instructions='Complete this assignment.',
			created_by=self.student_b,
			status=Assignment.Status.ACTIVE,
		)
		Submission.objects.create(
			assignment=assignment,
			learner=self.profile_a,
			answer_text='Submitted answer.',
			status=Submission.Status.SUBMITTED,
			submitted_at=timezone.now(),
		)
		lesson.status = Lesson.Status.COMPLETED
		lesson.save(update_fields=('status',))
		self.client.force_login(self.student_a)

		self.client.post(reverse('learning:lesson-status', args=(lesson.pk,)), {'status': Lesson.Status.IN_PROGRESS})

		lesson.refresh_from_db()
		self.assertEqual(lesson.status, Lesson.Status.COMPLETED)

	def test_learner_can_only_view_active_plan_and_plan_is_private_to_participants(self):
		partnership = self.create_direct_partnership(accept=True)
		direction = partnership.learning_directions.get(skill=self.python)
		active_plan = self.create_plan(direction)
		draft_plan = self.create_plan(direction, status=LearningPlan.Status.DRAFT)
		self.client.force_login(self.student_a)

		active_response = self.client.get(reverse('learning:plan-detail', args=(active_plan.pk,)))
		draft_response = self.client.get(reverse('learning:plan-detail', args=(draft_plan.pk,)))
		other_student_response = self.client.get(reverse('learning:plan-detail', args=(active_plan.pk,)))

		self.assertEqual(active_response.status_code, 200)
		self.assertEqual(draft_response.status_code, 404)
		self.client.force_login(self.student_c)
		other_student_response = self.client.get(reverse('learning:plan-detail', args=(active_plan.pk,)))
		self.assertEqual(other_student_response.status_code, 404)

	def test_unauthenticated_user_cannot_access_learning_pages(self):
		self.client.logout()

		for path in (reverse('learning:directions'), reverse('learning:plan-create')):
			with self.subTest(path=path):
				response = self.client.get(path)
				self.assertEqual(response.status_code, 302)
				self.assertIn(reverse('login'), response.url)

	def run_learning_workflow(self, partnership):
		direction = partnership.learning_directions.filter(skill=self.python).first()
		if direction is None:
			direction = create_directions_for_partnership(partnership)[0]
		plan = self.create_plan(direction)
		lesson = Lesson.objects.create(learning_plan=plan, title='Python practice', order=1)
		start = timezone.now() + timedelta(hours=2)
		end = start + timedelta(minutes=45)

		self.client.force_login(direction.teacher.user)
		session_response = self.client.post(
			reverse('learning:session-add', args=(direction.pk,)),
			{
				'title': 'Python practice session',
				'lesson': lesson.pk,
				'scheduled_start': start.strftime('%Y-%m-%dT%H:%M'),
				'scheduled_end': end.strftime('%Y-%m-%dT%H:%M'),
			},
		)
		session = direction.sessions.get(title='Python practice session')
		self.assertRedirects(session_response, reverse('learning:session-detail', args=(session.pk,)))

		assignment_response = self.client.post(
			reverse('learning:assignment-add', args=(lesson.pk,)),
			{
				'title': 'Python practice assignment',
				'instructions': 'Write a short Python function.',
				'status': Assignment.Status.ACTIVE,
			},
		)
		assignment = Assignment.objects.get(title='Python practice assignment')
		self.assertRedirects(
			assignment_response,
			reverse('learning:assignment-detail', args=(assignment.pk,)),
		)

		self.client.force_login(direction.learner.user)
		submission_response = self.client.post(
			reverse('learning:assignment-submit', args=(assignment.pk,)),
			{'action': 'submit', 'answer_text': 'def practice(): return True'},
		)
		submission = Submission.objects.get(assignment=assignment, learner=direction.learner)
		self.assertRedirects(
			submission_response,
			reverse('learning:assignment-detail', args=(assignment.pk,)),
		)

		self.client.force_login(direction.teacher.user)
		evaluation_response = self.client.post(
			reverse('learning:submission-evaluate', args=(submission.pk,)),
			{'score': '90', 'feedback': 'Good work.'},
		)
		self.assertRedirects(
			evaluation_response,
			reverse('learning:submission-detail', args=(submission.pk,)),
		)
		completion_response = self.client.post(
			reverse('learning:session-status', args=(session.pk,)),
			{'action': 'complete'},
		)
		self.assertRedirects(
			completion_response,
			reverse('learning:session-detail', args=(session.pk,)),
		)

		self.client.force_login(direction.learner.user)
		review_response = self.client.post(
			reverse('learning:review-add', args=(direction.pk,)),
			{'rating': 5, 'comment': 'Clear and useful.'},
		)
		self.assertRedirects(review_response, reverse('learning:directions'))
		session.refresh_from_db()
		submission.refresh_from_db()
		self.assertEqual(session.status, LearningSession.Status.COMPLETED)
		self.assertEqual(submission.status, Submission.Status.EVALUATED)
		self.assertTrue(Review.objects.filter(learning_direction=direction).exists())

		learner_types = set(
			Notification.objects.filter(recipient=direction.learner.user)
			.values_list('notification_type', flat=True)
		)
		self.assertTrue({
			Notification.NotificationType.ASSIGNMENT_CREATED,
			Notification.NotificationType.ASSIGNMENT_EVALUATED,
			Notification.NotificationType.SESSION_SCHEDULED,
			Notification.NotificationType.SESSION_COMPLETED,
		}.issubset(learner_types))
		self.assertTrue(Notification.objects.filter(
			recipient=direction.teacher.user,
			notification_type=Notification.NotificationType.ASSIGNMENT_SUBMITTED,
		).exists())
		self.assertTrue(Notification.objects.filter(
			recipient=direction.teacher.user,
			notification_type=Notification.NotificationType.REVIEW_RECEIVED,
		).exists())

	def test_direct_exchange_learning_workflow_completes_and_notifies(self):
		partnership = self.create_direct_partnership(accept=True)

		self.run_learning_workflow(partnership)

	def test_one_way_learning_workflow_completes_and_notifies(self):
		partnership = self.create_one_way_partnership()

		self.run_learning_workflow(partnership)


class LearningMaterialTests(TestCase):
	def setUp(self):
		self.learner = User.objects.create_user(username='learner', password='Strong-pass-2026!')
		self.teacher = User.objects.create_user(username='teacher', password='Strong-pass-2026!')
		self.outsider = User.objects.create_user(username='outsider', password='Strong-pass-2026!')
		self.learner_profile = self.learner.student_profile
		self.teacher_profile = self.teacher.student_profile
		self.outsider_profile = self.outsider.student_profile
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		OfferedSkill.objects.create(profile=self.teacher_profile, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.learner_profile, skill=self.python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		self.partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=self.learner_profile,
		)
		self.direction = LearningDirection.objects.create(
			partnership=self.partnership,
			teacher=self.teacher_profile,
			learner=self.learner_profile,
			skill=self.python,
		)
		self.plan = LearningPlan.objects.create(
			learning_direction=self.direction,
			title='Python Beginner',
			created_by=self.teacher,
			status=LearningPlan.Status.ACTIVE,
		)
		self.lesson = Lesson.objects.create(learning_plan=self.plan, title='Introduction', order=1)

	def create_link_material(self, *, title='Python Docs'):
		return LearningMaterial.objects.create(
			lesson=self.lesson,
			title=title,
			material_type=LearningMaterial.MaterialType.LINK,
			external_url='https://docs.example.test/python',
			created_by=self.teacher,
		)

	def test_teacher_can_create_valid_external_link_material(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Python Docs',
			'description': 'Official documentation.',
			'material_type': LearningMaterial.MaterialType.LINK,
			'external_url': 'https://docs.example.test/python',
		})

		material = LearningMaterial.objects.get(title='Python Docs')
		self.assertRedirects(response, reverse('learning:lesson-materials', args=(self.lesson.pk,)))
		self.assertEqual(material.lesson, self.lesson)
		self.assertEqual(material.created_by, self.teacher)
		self.assertEqual(material.external_url, 'https://docs.example.test/python')

	def test_link_requires_a_valid_url(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Invalid Link',
			'material_type': LearningMaterial.MaterialType.LINK,
			'external_url': 'not a URL',
		})

		self.assertEqual(response.status_code, 200)
		self.assertFalse(LearningMaterial.objects.filter(title='Invalid Link').exists())
		self.assertIn('external_url', response.context['form'].errors)

	def test_link_without_url_is_rejected(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Missing Link',
			'material_type': LearningMaterial.MaterialType.LINK,
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn('external_url', response.context['form'].errors)

	def test_unsupported_file_extension_is_rejected(self):
		self.client.force_login(self.teacher)
		upload = SimpleUploadedFile('program.exe', b'not allowed', content_type='application/octet-stream')

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Unsupported',
			'material_type': LearningMaterial.MaterialType.FILE,
			'file': upload,
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn('file', response.context['form'].errors)
		self.assertFalse(LearningMaterial.objects.filter(title='Unsupported').exists())

	def test_file_material_upload_and_protected_download(self):
		with TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				self.client.force_login(self.teacher)
				upload = SimpleUploadedFile('python-basics.pdf', b'%PDF-1.4 sample', content_type='application/pdf')
				response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
					'title': 'Python Basics PDF',
					'material_type': LearningMaterial.MaterialType.FILE,
					'file': upload,
				})
				material = LearningMaterial.objects.get(title='Python Basics PDF')
				self.assertRedirects(response, reverse('learning:lesson-materials', args=(self.lesson.pk,)))
				self.assertTrue(Path(media_root, material.file.name).is_file())
				self.assertFalse(LearningMaterialAccess.objects.filter(material=material).exists())

				self.client.force_login(self.learner)
				open_file = self.client.get(reverse('learning:material-file', args=(material.pk,)))
				download = self.client.get(reverse('learning:material-file', args=(material.pk,)) + '?download=1')
				raw_media_response = self.client.get(f'/media/{material.file.name}')
				try:
					self.assertEqual(open_file.status_code, 200)
					self.assertEqual(download.status_code, 200)
					self.assertEqual(raw_media_response.status_code, 200)
					self.assertIn('inline', open_file['Content-Disposition'])
					self.assertIn('attachment', download['Content-Disposition'])
					self.assertEqual(b''.join(open_file.streaming_content), b'%PDF-1.4 sample')
					self.assertEqual(b''.join(download.streaming_content), b'%PDF-1.4 sample')
					self.assertEqual(b''.join(raw_media_response.streaming_content), b'%PDF-1.4 sample')
				finally:
					open_file.close()
					download.close()
					raw_media_response.close()
				self.assertTrue(LearningMaterialAccess.objects.filter(material=material, learner=self.learner_profile).exists())
				self.assertEqual(LearningMaterialAccess.objects.filter(material=material).count(), 1)
				lesson_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
				self.assertContains(lesson_response, 'PDFs accessed: 1 / 1')
				self.assertContains(lesson_response, 'Accessed')
				self.lesson.refresh_from_db()
				self.assertEqual(self.lesson.progress_status, Lesson.Status.IN_PROGRESS)
				self.client.force_login(self.outsider)
				self.assertEqual(self.client.get(f'/media/{material.file.name}').status_code, 404)

	def test_file_material_requires_a_file(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'No File',
			'material_type': LearningMaterial.MaterialType.FILE,
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn('file', response.context['form'].errors)

	def test_material_type_must_be_valid(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Unknown Type',
			'material_type': 'OTHER',
		})

		self.assertEqual(response.status_code, 200)
		self.assertIn('material_type', response.context['form'].errors)

	def test_teacher_can_edit_own_material(self):
		material = self.create_link_material()
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-edit', args=(material.pk,)), {
			'title': 'Updated Python Docs',
			'material_type': LearningMaterial.MaterialType.LINK,
			'external_url': 'https://docs.example.test/updated',
		})

		self.assertRedirects(response, reverse('learning:lesson-materials', args=(self.lesson.pk,)))
		material.refresh_from_db()
		self.assertEqual(material.title, 'Updated Python Docs')
		self.assertEqual(material.external_url, 'https://docs.example.test/updated')

	def test_learner_cannot_create_edit_or_delete_material(self):
		material = self.create_link_material()
		self.client.force_login(self.learner)

		create_response = self.client.post(reverse('learning:material-add', args=(self.lesson.pk,)), {
			'title': 'Learner Material',
			'material_type': LearningMaterial.MaterialType.LINK,
			'external_url': 'https://example.test/',
		})
		edit_response = self.client.post(reverse('learning:material-edit', args=(material.pk,)), {
			'title': 'Changed',
			'material_type': LearningMaterial.MaterialType.LINK,
			'external_url': 'https://example.test/changed',
		})
		delete_response = self.client.post(reverse('learning:material-delete', args=(material.pk,)))

		self.assertEqual(create_response.status_code, 404)
		self.assertEqual(edit_response.status_code, 404)
		self.assertEqual(delete_response.status_code, 404)
		self.assertTrue(LearningMaterial.objects.filter(pk=material.pk).exists())

	def test_teacher_can_delete_own_material(self):
		material = self.create_link_material()
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:material-delete', args=(material.pk,)))

		self.assertRedirects(response, reverse('learning:lesson-materials', args=(self.lesson.pk,)))
		self.assertFalse(LearningMaterial.objects.filter(pk=material.pk).exists())

	def test_unrelated_student_cannot_access_material_or_file(self):
		material = self.create_link_material()
		self.client.force_login(self.outsider)

		responses = (
			self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,))),
			self.client.get(reverse('learning:lesson-materials', args=(self.lesson.pk,))),
			self.client.get(reverse('learning:material-edit', args=(material.pk,))),
			self.client.get(reverse('learning:material-file', args=(material.pk,))),
		)

		self.assertTrue(all(response.status_code == 404 for response in responses))

	def test_lesson_detail_displays_material_and_teacher_controls(self):
		material = self.create_link_material()
		self.client.force_login(self.teacher)
		teacher_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))

		self.assertContains(teacher_response, material.title)
		self.assertContains(teacher_response, 'Add Material')
		self.assertContains(teacher_response, 'Edit')
		self.assertContains(teacher_response, 'Learning plan progress')

		self.client.force_login(self.learner)
		learner_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
		self.assertContains(learner_response, material.title)
		self.assertNotContains(learner_response, 'Add Material')
		self.assertNotContains(learner_response, reverse('learning:material-edit', args=(material.pk,)))

	def test_receiver_can_see_lesson_files_and_assignment_resources_from_plan(self):
		with TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				material = LearningMaterial.objects.create(
					lesson=self.lesson,
					title='Chapter notes PDF',
					material_type=LearningMaterial.MaterialType.FILE,
					created_by=self.teacher,
				)
				material.file.save(
					'chapter-notes.pdf',
					SimpleUploadedFile('chapter-notes.pdf', b'%PDF chapter notes', content_type='application/pdf'),
				)
				assignment = Assignment.objects.create(
					lesson=self.lesson,
					title='Chapter exercise',
					instructions='Complete the chapter exercise.',
					created_by=self.teacher,
					status=Assignment.Status.ACTIVE,
				)
				assignment.resource_file.save(
					'exercise.pdf',
					SimpleUploadedFile('exercise.pdf', b'%PDF exercise', content_type='application/pdf'),
				)

				self.client.force_login(self.learner)
				plan_response = self.client.get(reverse('learning:plan-detail', args=(self.plan.pk,)))
				lesson_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))

				self.assertEqual(plan_response.status_code, 200)
				self.assertContains(plan_response, 'Chapter notes PDF')
				self.assertContains(plan_response, 'Chapter exercise')
				self.assertContains(plan_response, reverse('learning:material-file', args=(material.pk,)))
				self.assertContains(plan_response, reverse('learning:assignment-resource-file', args=(assignment.pk,)))
				self.assertEqual(lesson_response.status_code, 200)
				self.assertContains(lesson_response, 'Chapter notes PDF')
				self.assertContains(lesson_response, 'Chapter exercise')

				material_response = self.client.get(reverse('learning:material-file', args=(material.pk,)))
				assignment_response = self.client.get(reverse('learning:assignment-resource-file', args=(assignment.pk,)))
				try:
					self.assertEqual(material_response.status_code, 200)
					self.assertEqual(assignment_response.status_code, 200)
					self.assertEqual(b''.join(material_response.streaming_content), b'%PDF chapter notes')
					self.assertEqual(b''.join(assignment_response.streaming_content), b'%PDF exercise')
				finally:
					material_response.close()
					assignment_response.close()

	def test_learner_cannot_access_draft_plan_materials(self):
		self.plan.status = LearningPlan.Status.DRAFT
		self.plan.save(update_fields=('status',))
		self.client.force_login(self.learner)

		self.assertEqual(self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,))).status_code, 404)
		self.assertEqual(self.client.get(reverse('learning:lesson-materials', args=(self.lesson.pk,))).status_code, 404)

	def test_unauthenticated_users_cannot_access_material_pages_or_downloads(self):
		material = self.create_link_material()

		for path in (
			reverse('learning:lesson-materials', args=(self.lesson.pk,)),
			reverse('learning:material-add', args=(self.lesson.pk,)),
			reverse('learning:material-edit', args=(material.pk,)),
			reverse('learning:material-file', args=(material.pk,)),
		):
			with self.subTest(path=path):
				response = self.client.get(path)
				self.assertEqual(response.status_code, 302)
				self.assertIn(reverse('login'), response.url)


class AssignmentSubmissionTests(TestCase):
	def setUp(self):
		self.learner = User.objects.create_user(username='learner', password='Strong-pass-2026!')
		self.teacher = User.objects.create_user(username='teacher', password='Strong-pass-2026!')
		self.outsider = User.objects.create_user(username='outsider', password='Strong-pass-2026!')
		self.learner_profile = self.learner.student_profile
		self.teacher_profile = self.teacher.student_profile
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		OfferedSkill.objects.create(profile=self.teacher_profile, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.learner_profile, skill=self.python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=self.learner_profile,
		)
		direction = LearningDirection.objects.create(
			partnership=partnership,
			teacher=self.teacher_profile,
			learner=self.learner_profile,
			skill=self.python,
		)
		self.plan = LearningPlan.objects.create(
			learning_direction=direction,
			title='Python Beginner',
			created_by=self.teacher,
			status=LearningPlan.Status.ACTIVE,
		)
		self.lesson = Lesson.objects.create(learning_plan=self.plan, title='Practice', order=1)

	def create_assignment(self, *, title='Python Exercise', status=Assignment.Status.ACTIVE, **kwargs):
		return Assignment.objects.create(
			lesson=self.lesson,
			title=title,
			instructions='Write a small Python program.',
			created_by=self.teacher,
			status=status,
			**kwargs,
		)

	def submit(self, assignment, *, action='submit', **data):
		payload = {'action': action, **data}
		return self.client.post(reverse('learning:assignment-submit', args=(assignment.pk,)), payload)

	def test_teacher_can_create_assignment_with_optional_due_date(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:assignment-add', args=(self.lesson.pk,)), {
			'title': 'Python Exercise',
			'instructions': 'Write a loop.',
			'due_date': '2030-08-01T14:30',
			'status': Assignment.Status.ACTIVE,
		})

		assignment = Assignment.objects.get(title='Python Exercise')
		self.assertRedirects(response, reverse('learning:assignment-detail', args=(assignment.pk,)))
		self.assertEqual(assignment.lesson, self.lesson)
		self.assertEqual(assignment.created_by, self.teacher)
		self.assertEqual(assignment.due_date.strftime('%Y-%m-%d %H:%M'), '2030-08-01 14:30')
		notification = Notification.objects.get(recipient=self.learner)
		self.assertEqual(notification.notification_type, Notification.NotificationType.ASSIGNMENT_CREATED)

	def test_due_date_is_optional_and_required_fields_are_validated(self):
		self.client.force_login(self.teacher)
		valid_response = self.client.post(reverse('learning:assignment-add', args=(self.lesson.pk,)), {
			'title': 'Open-ended',
			'instructions': 'Practice when ready.',
			'due_date': '',
			'status': Assignment.Status.DRAFT,
		})
		invalid_response = self.client.post(reverse('learning:assignment-add', args=(self.lesson.pk,)), {
			'title': '',
			'instructions': '',
			'status': Assignment.Status.ACTIVE,
		})

		self.assertEqual(valid_response.status_code, 302)
		self.assertIsNone(Assignment.objects.get(title='Open-ended').due_date)
		self.assertEqual(invalid_response.status_code, 200)
		self.assertIn('title', invalid_response.context['form'].errors)
		self.assertIn('instructions', invalid_response.context['form'].errors)

	def test_teacher_can_edit_and_delete_own_assignment(self):
		assignment = self.create_assignment(status=Assignment.Status.DRAFT)
		self.client.force_login(self.teacher)

		edit_response = self.client.post(reverse('learning:assignment-edit', args=(assignment.pk,)), {
			'title': 'Updated Exercise',
			'instructions': 'Write a function.',
			'status': Assignment.Status.CLOSED,
		})
		assignment.refresh_from_db()
		self.assertRedirects(edit_response, reverse('learning:assignment-detail', args=(assignment.pk,)))
		self.assertEqual(assignment.title, 'Updated Exercise')
		self.assertEqual(assignment.status, Assignment.Status.CLOSED)

		delete_response = self.client.post(reverse('learning:assignment-delete', args=(assignment.pk,)))
		self.assertRedirects(delete_response, reverse('learning:lesson-assignments', args=(self.lesson.pk,)))
		self.assertFalse(Assignment.objects.filter(pk=assignment.pk).exists())

	def test_activating_a_draft_assignment_notifies_the_learner_once(self):
		assignment = self.create_assignment(status=Assignment.Status.DRAFT)
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:assignment-edit', args=(assignment.pk,)), {
			'title': assignment.title,
			'instructions': assignment.instructions,
			'status': Assignment.Status.ACTIVE,
			'due_date': '',
		})

		self.assertRedirects(response, reverse('learning:assignment-detail', args=(assignment.pk,)))
		notifications = Notification.objects.filter(
			recipient=self.learner,
			notification_type=Notification.NotificationType.ASSIGNMENT_CREATED,
		)
		self.assertEqual(notifications.count(), 1)

	def test_learner_cannot_create_edit_or_delete_assignment(self):
		assignment = self.create_assignment()
		self.client.force_login(self.learner)

		create_response = self.client.post(reverse('learning:assignment-add', args=(self.lesson.pk,)), {
			'title': 'Not Allowed',
			'instructions': 'No.',
			'status': Assignment.Status.ACTIVE,
		})
		edit_response = self.client.post(reverse('learning:assignment-edit', args=(assignment.pk,)), {
			'title': 'Changed',
			'instructions': 'Changed',
			'status': Assignment.Status.CLOSED,
		})
		delete_response = self.client.post(reverse('learning:assignment-delete', args=(assignment.pk,)))

		self.assertEqual(create_response.status_code, 404)
		self.assertEqual(edit_response.status_code, 404)
		self.assertEqual(delete_response.status_code, 404)
		self.assertFalse(Assignment.objects.filter(title='Not Allowed').exists())
		assignment.refresh_from_db()
		self.assertEqual(assignment.status, Assignment.Status.ACTIVE)

	def test_draft_hidden_active_visible_and_closed_read_only(self):
		draft = self.create_assignment(title='Draft Exercise', status=Assignment.Status.DRAFT)
		active = self.create_assignment(title='Active Exercise')
		closed = self.create_assignment(title='Closed Exercise', status=Assignment.Status.CLOSED)
		self.client.force_login(self.learner)

		lesson_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
		draft_response = self.client.get(reverse('learning:assignment-detail', args=(draft.pk,)))
		active_response = self.client.get(reverse('learning:assignment-detail', args=(active.pk,)))
		closed_response = self.client.get(reverse('learning:assignment-detail', args=(closed.pk,)))
		closed_submit = self.submit(closed, answer_text='Late answer')

		self.assertNotContains(lesson_response, 'Draft Exercise')
		self.assertContains(lesson_response, 'Active Exercise')
		self.assertEqual(draft_response.status_code, 404)
		self.assertEqual(active_response.status_code, 200)
		self.assertContains(active_response, 'Submit Assignment')
		self.assertEqual(closed_response.status_code, 200)
		self.assertNotContains(closed_response, 'Submit Assignment')
		self.assertEqual(closed_submit.status_code, 404)

	def test_assignment_detail_and_submission_pages_are_participant_scoped(self):
		assignment = self.create_assignment()
		self.client.force_login(self.outsider)

		self.assertEqual(self.client.get(reverse('learning:assignment-detail', args=(assignment.pk,))).status_code, 404)
		self.assertEqual(self.client.get(reverse('learning:assignment-submit', args=(assignment.pk,))).status_code, 404)

	def test_learner_can_save_draft_then_submit_answer(self):
		assignment = self.create_assignment()
		self.client.force_login(self.learner)

		draft_response = self.submit(assignment, action='draft', answer_text='Draft response')
		submission = Submission.objects.get(assignment=assignment, learner=self.learner_profile)
		self.assertRedirects(draft_response, reverse('learning:assignment-detail', args=(assignment.pk,)))
		self.assertEqual(submission.status, Submission.Status.DRAFT)
		self.assertIsNone(submission.submitted_at)
		self.assertFalse(Notification.objects.filter(
			recipient=self.teacher,
			notification_type=Notification.NotificationType.ASSIGNMENT_SUBMITTED,
		).exists())

		submit_response = self.submit(assignment, action='submit', answer_text='Final response')
		submission.refresh_from_db()
		self.assertRedirects(submit_response, reverse('learning:assignment-detail', args=(assignment.pk,)))
		self.assertEqual(submission.status, Submission.Status.SUBMITTED)
		self.assertIsNotNone(submission.submitted_at)
		self.assertEqual(submission.answer_text, 'Final response')
		self.assertEqual(Submission.objects.filter(assignment=assignment, learner=self.learner_profile).count(), 1)
		self.assertEqual(Notification.objects.filter(
			recipient=self.teacher,
			notification_type=Notification.NotificationType.ASSIGNMENT_SUBMITTED,
		).count(), 1)

		self.client.post(reverse('learning:assignment-submit', args=(assignment.pk,)), {
			'action': 'submit',
			'answer_text': 'Attempt to change final submission',
		})
		submission.refresh_from_db()
		self.assertEqual(submission.answer_text, 'Final response')

	def test_empty_submission_is_rejected(self):
		assignment = self.create_assignment()
		self.client.force_login(self.learner)

		response = self.submit(assignment, action='draft', answer_text='   ')

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.context['submission_form'].non_field_errors())
		self.assertFalse(Submission.objects.filter(assignment=assignment).exists())

	def test_file_only_and_answer_plus_file_submissions_work(self):
		with TemporaryDirectory() as media_root:
			with override_settings(MEDIA_ROOT=media_root):
				self.client.force_login(self.learner)
				file_only_assignment = self.create_assignment(title='File Only')
				file_only = SimpleUploadedFile('work.pdf', b'%PDF-1.4 work', content_type='application/pdf')
				file_response = self.client.post(
					reverse('learning:assignment-submit', args=(file_only_assignment.pk,)),
					{'action': 'submit', 'file': file_only},
				)
				file_submission = Submission.objects.get(assignment=file_only_assignment)
				self.assertRedirects(file_response, reverse('learning:assignment-detail', args=(file_only_assignment.pk,)))
				self.assertTrue(Path(media_root, file_submission.file.name).is_file())
				download = self.client.get(reverse('learning:submission-file', args=(file_submission.pk,)))
				raw_download = self.client.get(f'/media/{file_submission.file.name}')
				try:
					self.assertEqual(download.status_code, 200)
					self.assertEqual(raw_download.status_code, 200)
					self.assertEqual(b''.join(download.streaming_content), b'%PDF-1.4 work')
					self.assertEqual(b''.join(raw_download.streaming_content), b'%PDF-1.4 work')
				finally:
					download.close()
					raw_download.close()
				self.client.force_login(self.outsider)
				self.assertEqual(self.client.get(reverse('learning:submission-file', args=(file_submission.pk,))).status_code, 404)
				self.assertEqual(self.client.get(f'/media/{file_submission.file.name}').status_code, 404)
				self.client.force_login(self.learner)

				both_assignment = self.create_assignment(title='Answer and File')
				both_file = SimpleUploadedFile('answer.txt', b'file answer', content_type='text/plain')
				both_response = self.client.post(
					reverse('learning:assignment-submit', args=(both_assignment.pk,)),
					{'action': 'submit', 'answer_text': 'Written answer', 'file': both_file},
				)
				both_submission = Submission.objects.get(assignment=both_assignment)
				self.assertRedirects(both_response, reverse('learning:assignment-detail', args=(both_assignment.pk,)))
				self.assertEqual(both_submission.answer_text, 'Written answer')
				self.assertTrue(both_submission.file.name)

	def test_submission_file_validation_and_size_limit(self):
		assignment = self.create_assignment()
		self.client.force_login(self.learner)
		invalid_file = SimpleUploadedFile('malware.exe', b'no', content_type='application/octet-stream')
		invalid_response = self.client.post(reverse('learning:assignment-submit', args=(assignment.pk,)), {
			'action': 'draft',
			'file': invalid_file,
		})
		self.assertEqual(invalid_response.status_code, 200)
		self.assertIn('file', invalid_response.context['submission_form'].errors)

		large_file = SimpleUploadedFile('large.txt', b'x' * (20 * 1024 * 1024 + 1), content_type='text/plain')
		large_response = self.client.post(reverse('learning:assignment-submit', args=(assignment.pk,)), {
			'action': 'draft',
			'file': large_file,
		})
		self.assertEqual(large_response.status_code, 200)
		self.assertIn('file', large_response.context['submission_form'].errors)

	def test_submission_model_enforces_one_record_per_learner(self):
		assignment = self.create_assignment()
		Submission.objects.create(assignment=assignment, learner=self.learner_profile, answer_text='One')

		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				Submission.objects.create(assignment=assignment, learner=self.learner_profile, answer_text='Two')

	def test_teacher_can_view_own_submissions_but_unrelated_student_cannot(self):
		assignment = self.create_assignment()
		submission = Submission.objects.create(
			assignment=assignment,
			learner=self.learner_profile,
			answer_text='Answer',
			status=Submission.Status.SUBMITTED,
		)
		self.client.force_login(self.teacher)
		teacher_list = self.client.get(reverse('learning:assignment-submissions', args=(assignment.pk,)))
		teacher_detail = self.client.get(reverse('learning:submission-detail', args=(submission.pk,)))
		self.assertContains(teacher_list, self.learner.username)
		self.assertEqual(teacher_detail.status_code, 200)

		self.client.force_login(self.outsider)
		self.assertEqual(self.client.get(reverse('learning:assignment-submissions', args=(assignment.pk,))).status_code, 404)
		self.assertEqual(self.client.get(reverse('learning:submission-detail', args=(submission.pk,))).status_code, 404)
		self.assertEqual(self.client.get(reverse('learning:submission-file', args=(submission.pk,))).status_code, 404)

	def test_learner_cannot_submit_for_another_learner(self):
		assignment = self.create_assignment()
		self.client.force_login(self.outsider)

		response = self.client.post(reverse('learning:assignment-submit', args=(assignment.pk,)), {
			'action': 'submit',
			'answer_text': 'Pretending to be the assigned learner.',
		})

		self.assertEqual(response.status_code, 404)
		self.assertFalse(Submission.objects.filter(assignment=assignment).exists())

	def test_unauthenticated_users_cannot_access_assignment_or_submission_pages(self):
		assignment = self.create_assignment()
		submission = Submission.objects.create(assignment=assignment, learner=self.learner_profile, answer_text='Draft')

		for path in (
			reverse('learning:assignment-detail', args=(assignment.pk,)),
			reverse('learning:assignment-submit', args=(assignment.pk,)),
			reverse('learning:submission-detail', args=(submission.pk,)),
		):
			with self.subTest(path=path):
				response = self.client.get(path)
				self.assertEqual(response.status_code, 302)
				self.assertIn(reverse('login'), response.url)

	def test_assignment_detail_and_teacher_controls_render(self):
		assignment = self.create_assignment()
		self.client.force_login(self.teacher)
		teacher_response = self.client.get(reverse('learning:assignment-detail', args=(assignment.pk,)))
		self.assertContains(teacher_response, 'Edit')
		self.assertContains(teacher_response, 'View Submissions')
		teacher_lesson_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
		self.assertContains(teacher_lesson_response, 'Create Assignment')

		self.client.force_login(self.learner)
		learner_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
		self.assertContains(learner_response, assignment.title)
		self.assertNotContains(learner_response, 'Create Assignment')
		draft_assignment = self.create_assignment(title='Draft Only', status=Assignment.Status.DRAFT)
		learner_response = self.client.get(reverse('learning:lesson-detail', args=(self.lesson.pk,)))
		self.assertNotContains(learner_response, draft_assignment.title)

	def test_admin_can_view_assignment_and_submission_changelists(self):
		admin_user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)

		assignment_response = self.client.get(reverse('admin:learning_assignment_changelist'))
		submission_response = self.client.get(reverse('admin:learning_submission_changelist'))

		self.assertEqual(assignment_response.status_code, 200)
		self.assertEqual(submission_response.status_code, 200)


class SessionTests(TestCase):
	def setUp(self):
		self.learner = User.objects.create_user(username='learner-session', password='Strong-pass-2026!')
		self.teacher = User.objects.create_user(username='teacher-session', password='Strong-pass-2026!')
		self.teacher_profile = self.teacher.student_profile
		self.learner_profile = self.learner.student_profile
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		OfferedSkill.objects.create(profile=self.teacher_profile, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.learner_profile, skill=self.python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			compatibility_score=80,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=self.learner_profile,
		)
		self.direction = LearningDirection.objects.create(
			partnership=partnership,
			teacher=self.teacher_profile,
			learner=self.learner_profile,
			skill=self.python,
		)
		plan = LearningPlan.objects.create(
			learning_direction=self.direction,
			title='Python Beginner',
			created_by=self.teacher,
			status=LearningPlan.Status.ACTIVE,
		)
		self.lesson = Lesson.objects.create(learning_plan=plan, title='Practice', order=1)
		self.base_start = timezone.now() + timedelta(hours=1)
		self.base_end = self.base_start + timedelta(minutes=45)

	def test_teacher_can_schedule_sessions_for_their_direction(self):
		self.client.force_login(self.teacher)
		form_response = self.client.get(reverse('learning:session-add', args=(self.direction.pk,)))
		self.assertEqual(form_response.status_code, 200)
		self.assertContains(form_response, 'learning-session-form-card')
		self.assertContains(form_response, 'Schedule a learning session')
		self.assertContains(form_response, 'learning-session-submit-button')

		response = self.client.post(reverse('learning:session-add', args=(self.direction.pk,)), {
			'title': 'Python sprint',
			'description': 'Focus on lists and loops.',
			'lesson': self.lesson.pk,
			'scheduled_start': self.base_start.strftime('%Y-%m-%dT%H:%M'),
			'scheduled_end': self.base_end.strftime('%Y-%m-%dT%H:%M'),
			'meeting_url': 'https://meet.google.com/example',
		})

		session = self.direction.sessions.get(title='Python sprint')
		self.assertRedirects(response, reverse('learning:session-detail', args=(session.pk,)))
		self.assertEqual(session.created_by, self.teacher)
		self.assertEqual(session.lesson, self.lesson)
		self.assertEqual(session.status, 'SCHEDULED')
		notification = Notification.objects.get(recipient=self.learner)
		self.assertEqual(notification.notification_type, Notification.NotificationType.SESSION_SCHEDULED)

	def test_updating_a_session_notifies_the_learner(self):
		session = self.direction.sessions.create(
			title='Python sprint',
			lesson=self.lesson,
			scheduled_start=self.base_start,
			scheduled_end=self.base_end,
			created_by=self.teacher,
		)
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:session-edit', args=(session.pk,)), {
			'title': 'Updated Python sprint',
			'lesson': self.lesson.pk,
			'scheduled_start': self.base_start.strftime('%Y-%m-%dT%H:%M'),
			'scheduled_end': self.base_end.strftime('%Y-%m-%dT%H:%M'),
			'meeting_url': '',
			'description': '',
		})

		self.assertRedirects(response, reverse('learning:session-detail', args=(session.pk,)))
		notification = Notification.objects.get(recipient=self.learner)
		self.assertEqual(notification.notification_type, Notification.NotificationType.SESSION_UPDATED)

	def test_learner_sees_only_direction_sessions_and_can_join_when_live(self):
		self.client.force_login(self.learner)
		session = self.direction.sessions.create(
			title='Scheduled review',
			description='We will review loops.',
			lesson=self.lesson,
			scheduled_start=timezone.now() - timedelta(minutes=10),
			scheduled_end=timezone.now() + timedelta(minutes=35),
			meeting_url='https://meet.google.com/example',
			created_by=self.teacher,
		)
		response = self.client.get(reverse('learning:session-detail', args=(session.pk,)))
		self.assertContains(response, 'Join session')
		self.assertTrue(response.context['can_join'])
		self.assertEqual(response.context['is_learner'], True)
		list_response = self.client.get(reverse('learning:sessions'))
		self.assertContains(list_response, '/static/css/learning.css?v=20261005-5')
		self.assertContains(list_response, 'ON YOUR CALENDAR')
		self.assertContains(list_response, 'Your shared learning calendar')
		self.assertContains(list_response, reverse('learning:session-detail', args=(session.pk,)))
		self.assertContains(list_response, 'href="https://meet.google.com/example"')
		self.assertContains(list_response, 'LIVE NOW')
		self.assertContains(list_response, 'Join session')

	def test_learner_cannot_join_outside_the_scheduled_window(self):
		self.client.force_login(self.learner)
		for title, start, end in (
			('Future session', timezone.now() + timedelta(hours=1), timezone.now() + timedelta(hours=2)),
			('Ended session', timezone.now() - timedelta(hours=2), timezone.now() - timedelta(hours=1)),
		):
			with self.subTest(title=title):
				session = self.direction.sessions.create(
					title=title,
					scheduled_start=start,
					scheduled_end=end,
					meeting_url='https://meet.google.com/example',
					created_by=self.teacher,
				)
				response = self.client.get(reverse('learning:session-detail', args=(session.pk,)))
				self.assertEqual(response.status_code, 200)
				self.assertContains(response, 'https://meet.google.com/example')
				self.assertNotContains(response, 'Join session')
				self.assertFalse(response.context['can_join'])
				if title == 'Future session':
					list_response = self.client.get(reverse('learning:sessions'))
					self.assertContains(list_response, 'href="https://meet.google.com/example"')

	def test_outsider_cannot_view_or_list_a_learner_session(self):
		outsider = User.objects.create_user(username='outsider-session', password='Strong-pass-2026!')
		session = self.direction.sessions.create(
			title='Private session',
			scheduled_start=self.base_start,
			scheduled_end=self.base_end,
			created_by=self.teacher,
		)
		self.client.force_login(outsider)

		detail_response = self.client.get(reverse('learning:session-detail', args=(session.pk,)))
		list_response = self.client.get(reverse('learning:sessions'))
		self.assertEqual(detail_response.status_code, 404)
		self.assertEqual(list_response.status_code, 200)
		self.assertNotContains(list_response, 'Private session')

	def test_teacher_can_cancel_or_complete_a_session(self):
		session = self.direction.sessions.create(
			title='Wrap-up call',
			scheduled_start=self.base_start,
			scheduled_end=self.base_end,
			created_by=self.teacher,
		)
		self.client.force_login(self.teacher)
		cancel_response = self.client.post(reverse('learning:session-status', args=(session.pk,)), {'action': 'cancel'})
		self.assertRedirects(cancel_response, reverse('learning:session-detail', args=(session.pk,)))
		session.refresh_from_db()
		self.assertEqual(session.status, 'CANCELLED')

		complete_response = self.client.post(reverse('learning:session-status', args=(session.pk,)), {'action': 'complete'})
		self.assertRedirects(complete_response, reverse('learning:session-detail', args=(session.pk,)))
		session.refresh_from_db()
		self.assertEqual(session.status, 'COMPLETED')
		self.assertEqual(
			set(Notification.objects.filter(recipient=self.learner).values_list('notification_type', flat=True)),
			{
				Notification.NotificationType.SESSION_CANCELLED,
				Notification.NotificationType.SESSION_COMPLETED,
			},
		)
		self.client.post(reverse('learning:session-status', args=(session.pk,)), {'action': 'complete'})
		self.assertEqual(
			Notification.objects.filter(recipient=self.learner).count(),
			2,
		)

	def test_session_overlaps_are_rejected_within_direction(self):
		self.direction.sessions.create(
			title='First session',
			scheduled_start=self.base_start,
			scheduled_end=self.base_end,
			created_by=self.teacher,
		)
		self.client.force_login(self.teacher)
		response = self.client.post(reverse('learning:session-add', args=(self.direction.pk,)), {
			'title': 'Second session',
			'scheduled_start': (self.base_start + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M'),
			'scheduled_end': (self.base_end + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M'),
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'overlaps with another scheduled session')

	def test_teacher_cannot_create_session_for_unowned_direction(self):
		other_teacher = User.objects.create_user(username='other-teacher', password='Strong-pass-2026!')
		other_profile = other_teacher.student_profile
		other_python, _ = Skill.objects.get_or_create(
			name='SQL',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		OfferedSkill.objects.create(profile=other_profile, skill=other_python, proficiency='ADVANCED')
		other_match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=other_profile,
			compatibility_score=90,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': other_python.pk, 'skill': 'SQL'}],
				'student_two_learns_from_one': [],
			},
		)
		other_partnership = LearningPartnership.objects.create(
			match=other_match,
			student_one=self.learner_profile,
			student_two=other_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=other_profile,
			primary_learner=self.learner_profile,
		)
		other_direction = LearningDirection.objects.create(
			partnership=other_partnership,
			teacher=other_profile,
			learner=self.learner_profile,
			skill=other_python,
		)
		self.client.force_login(self.teacher)
		response = self.client.get(reverse('learning:session-add', args=(other_direction.pk,)))
		self.assertEqual(response.status_code, 404)


class EvaluationTests(TestCase):
	def setUp(self):
		self.learner = User.objects.create_user(username='learner', password='Strong-pass-2026!')
		self.teacher = User.objects.create_user(username='teacher', password='Strong-pass-2026!')
		self.outsider = User.objects.create_user(username='outsider', password='Strong-pass-2026!')
		self.learner_profile = self.learner.student_profile
		self.teacher_profile = self.teacher.student_profile
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		OfferedSkill.objects.create(profile=self.teacher_profile, skill=self.python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=self.learner_profile, skill=self.python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=self.learner_profile,
		)
		direction = LearningDirection.objects.create(
			partnership=partnership,
			teacher=self.teacher_profile,
			learner=self.learner_profile,
			skill=self.python,
		)
		plan = LearningPlan.objects.create(
			learning_direction=direction,
			title='Python Beginner',
			created_by=self.teacher,
			status=LearningPlan.Status.ACTIVE,
		)
		self.lesson = Lesson.objects.create(learning_plan=plan, title='Practice', order=1)
		self.assignment = Assignment.objects.create(
			lesson=self.lesson,
			title='Python Exercise',
			instructions='Write a small Python program.',
			created_by=self.teacher,
			status=Assignment.Status.ACTIVE,
		)
		self.submission = Submission.objects.create(
			assignment=self.assignment,
			learner=self.learner_profile,
			answer_text='My answer',
			status=Submission.Status.SUBMITTED,
			submitted_at=timezone.now(),
		)

	def evaluate(self, submission=None, **data):
		return self.client.post(
			reverse('learning:submission-evaluate', args=((submission or self.submission).pk,)),
			data,
		)

	def test_teacher_evaluates_own_submission_and_status_updates(self):
		self.client.force_login(self.teacher)

		response = self.evaluate(score='87.50', feedback='Good work. Review edge cases.', evaluator=self.outsider.pk)

		evaluation = Evaluation.objects.get(submission=self.submission)
		self.submission.refresh_from_db()
		self.assertRedirects(response, reverse('learning:submission-detail', args=(self.submission.pk,)))
		self.assertEqual(evaluation.evaluator, self.teacher)
		self.assertEqual(evaluation.score, Decimal('87.50'))
		self.assertEqual(evaluation.feedback, 'Good work. Review edge cases.')
		self.assertEqual(evaluation.status, Evaluation.Status.EVALUATED)
		self.assertEqual(self.submission.status, Submission.Status.EVALUATED)
		notification = Notification.objects.get(recipient=self.learner)
		self.assertEqual(notification.notification_type, Notification.NotificationType.ASSIGNMENT_EVALUATED)

	def test_editing_an_evaluation_does_not_duplicate_its_notification(self):
		self.client.force_login(self.teacher)

		self.evaluate(score='80', feedback='Good start.')
		self.evaluate(score='90', feedback='Improved after revision.')

		self.assertEqual(Notification.objects.filter(
			recipient=self.learner,
			notification_type=Notification.NotificationType.ASSIGNMENT_EVALUATED,
		).count(), 1)

	def test_feedback_only_evaluation_is_valid(self):
		self.client.force_login(self.teacher)

		response = self.evaluate(feedback='Please add error handling.')

		evaluation = Evaluation.objects.get(submission=self.submission)
		self.assertRedirects(response, reverse('learning:submission-detail', args=(self.submission.pk,)))
		self.assertIsNone(evaluation.score)
		self.assertEqual(evaluation.status, Evaluation.Status.EVALUATED)

	def test_score_boundaries_zero_and_100_are_accepted(self):
		self.client.force_login(self.teacher)
		zero_response = self.evaluate(score='0', feedback='Review the requirements.')
		zero_evaluation = Evaluation.objects.get(submission=self.submission)
		self.assertRedirects(zero_response, reverse('learning:submission-detail', args=(self.submission.pk,)))
		self.assertEqual(zero_evaluation.score, Decimal('0.00'))

		other_assignment = Assignment.objects.create(
			lesson=self.lesson,
			title='Second Exercise',
			instructions='Another program.',
			created_by=self.teacher,
			status=Assignment.Status.ACTIVE,
		)
		other_submission = Submission.objects.create(
			assignment=other_assignment,
			learner=self.learner_profile,
			answer_text='Another answer',
			status=Submission.Status.SUBMITTED,
			submitted_at=timezone.now(),
		)
		max_response = self.evaluate(other_submission, score='100', feedback='Excellent.')
		self.assertRedirects(max_response, reverse('learning:submission-detail', args=(other_submission.pk,)))
		self.assertEqual(Evaluation.objects.get(submission=other_submission).score, Decimal('100.00'))

	def test_negative_and_over_100_scores_are_rejected(self):
		self.client.force_login(self.teacher)

		for score in ('-0.01', '100.01'):
			with self.subTest(score=score):
				response = self.evaluate(score=score, feedback='Feedback.')
				self.assertEqual(response.status_code, 200)
				self.assertIn('score', response.context['form'].errors)
				self.assertFalse(Evaluation.objects.filter(submission=self.submission).exists())

	def test_evaluation_requires_score_or_feedback(self):
		self.client.force_login(self.teacher)

		response = self.evaluate(score='', feedback='  ')

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.context['form'].non_field_errors())
		self.assertFalse(Evaluation.objects.filter(submission=self.submission).exists())

	def test_draft_submission_cannot_be_evaluated(self):
		draft_assignment = Assignment.objects.create(
			lesson=self.lesson,
			title='Draft Assignment',
			instructions='Draft work.',
			created_by=self.teacher,
			status=Assignment.Status.ACTIVE,
		)
		draft = Submission.objects.create(
			assignment=draft_assignment,
			learner=self.learner_profile,
			answer_text='Draft answer',
			status=Submission.Status.DRAFT,
		)
		self.client.force_login(self.teacher)

		self.assertEqual(self.client.get(reverse('learning:submission-evaluate', args=(draft.pk,))).status_code, 404)

	def test_submission_cannot_be_marked_evaluated_before_being_submitted(self):
		invalid_submission = Submission(
			assignment=self.assignment,
			learner=self.learner_profile,
			answer_text='Answer ready for review.',
			status=Submission.Status.EVALUATED,
		)

		with self.assertRaises(ValidationError):
			invalid_submission.full_clean()

	def test_learner_cannot_edit_evaluated_submission(self):
		self.submission.status = Submission.Status.EVALUATED
		self.submission.save(update_fields=('status',))
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Nice work.',
			score=85,
			status=Evaluation.Status.EVALUATED,
		)
		self.client.force_login(self.learner)

		response = self.client.post(reverse('learning:assignment-submit', args=(self.assignment.pk,)), {
			'action': 'draft',
			'answer_text': 'Attempted edit after evaluation',
		})

		self.assertRedirects(response, reverse('learning:assignment-detail', args=(self.assignment.pk,)))
		self.submission.refresh_from_db()
		self.assertEqual(self.submission.answer_text, 'My answer')

	def test_learner_cannot_create_edit_or_delete_evaluation(self):
		evaluation = Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Already evaluated.',
			score=80,
			status=Evaluation.Status.EVALUATED,
		)
		self.client.force_login(self.learner)

		create_response = self.client.post(reverse('learning:submission-evaluate', args=(self.submission.pk,)), {
			'feedback': 'Learner cannot grade self.',
		})
		view_response = self.client.get(reverse('learning:submission-evaluate', args=(self.submission.pk,)))

		self.assertEqual(create_response.status_code, 404)
		self.assertEqual(view_response.status_code, 404)
		self.assertTrue(Evaluation.objects.filter(pk=evaluation.pk).exists())
		self.assertEqual(evaluation.evaluator, self.teacher)

	def test_unrelated_student_cannot_view_evaluation(self):
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Private feedback.',
			status=Evaluation.Status.EVALUATED,
		)
		self.submission.status = Submission.Status.EVALUATED
		self.submission.save(update_fields=('status',))
		self.client.force_login(self.outsider)

		self.assertEqual(self.client.get(reverse('learning:submission-detail', args=(self.submission.pk,))).status_code, 404)

	def test_teacher_cannot_evaluate_unrelated_submission(self):
		other = User.objects.create_user(username='other-teacher', password='Strong-pass-2026!')
		other_profile = other.student_profile
		other_match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=other_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		other_partnership = LearningPartnership.objects.create(
			match=other_match,
			student_one=self.learner_profile,
			student_two=other_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=other_profile,
			primary_learner=self.learner_profile,
		)
		other_direction = LearningDirection.objects.create(
			partnership=other_partnership,
			teacher=other_profile,
			learner=self.learner_profile,
			skill=self.python,
		)
		other_plan = LearningPlan.objects.create(
			learning_direction=other_direction,
			title='Other Plan',
			created_by=other,
		)
		other_lesson = Lesson.objects.create(learning_plan=other_plan, title='Other Lesson', order=1)
		other_assignment = Assignment.objects.create(
			lesson=other_lesson,
			title='Other Assignment',
			instructions='Other work.',
			created_by=other,
		)
		other_submission = Submission.objects.create(
			assignment=other_assignment,
			learner=self.learner_profile,
			answer_text='Answer',
			status=Submission.Status.SUBMITTED,
			submitted_at=timezone.now(),
		)
		self.client.force_login(self.teacher)

		self.assertEqual(self.client.get(reverse('learning:submission-evaluate', args=(other_submission.pk,))).status_code, 404)

	def test_evaluation_is_unique_and_cannot_be_created_by_another_evaluator(self):
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Evaluated.',
			score=50,
			status=Evaluation.Status.EVALUATED,
		)
		with self.assertRaises(IntegrityError):
			with transaction.atomic():
				Evaluation.objects.create(
					submission=self.submission,
					evaluator=self.outsider,
					feedback='Duplicate.',
				)

		invalid = Evaluation(
			submission=self.submission,
			evaluator=self.outsider,
			feedback='Wrong evaluator.',
			status=Evaluation.Status.EVALUATED,
		)
		with self.assertRaises(ValidationError):
			invalid.full_clean()

	def test_evaluator_and_status_cannot_be_supplied_by_form(self):
		self.client.force_login(self.teacher)

		response = self.client.post(reverse('learning:submission-evaluate', args=(self.submission.pk,)), {
			'evaluator': self.outsider.pk,
			'status': Evaluation.Status.PENDING,
			'score': '90',
			'feedback': 'Reviewed.',
		})

		evaluation = Evaluation.objects.get(submission=self.submission)
		self.assertRedirects(response, reverse('learning:submission-detail', args=(self.submission.pk,)))
		self.assertEqual(evaluation.evaluator, self.teacher)
		self.assertEqual(evaluation.status, Evaluation.Status.EVALUATED)

	def test_learner_sees_only_their_own_feedback_and_score(self):
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Strong solution.',
			score=Decimal('0.00'),
			status=Evaluation.Status.EVALUATED,
		)
		self.submission.status = Submission.Status.EVALUATED
		self.submission.save(update_fields=('status',))
		self.client.force_login(self.learner)

		response = self.client.get(reverse('learning:submission-detail', args=(self.submission.pk,)))

		self.assertContains(response, 'Strong solution.')
		self.assertContains(response, '0.00 / 100')
		self.assertNotContains(response, 'Edit Evaluation')

	def test_feedback_without_score_label_renders(self):
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='No numeric score needed.',
			status=Evaluation.Status.EVALUATED,
		)
		self.submission.status = Submission.Status.EVALUATED
		self.submission.save(update_fields=('status',))
		self.client.force_login(self.learner)

		response = self.client.get(reverse('learning:submission-detail', args=(self.submission.pk,)))

		self.assertContains(response, 'Feedback provided without a score.')
		self.assertContains(response, 'No numeric score needed.')

	def test_teacher_submission_list_shows_evaluation_state_and_controls(self):
		self.client.force_login(self.teacher)
		pending_response = self.client.get(reverse('learning:assignment-submissions', args=(self.assignment.pk,)))
		self.assertContains(pending_response, 'Evaluate Submission')
		self.client.post(reverse('learning:submission-evaluate', args=(self.submission.pk,)), {
			'score': '95',
			'feedback': 'Excellent.',
		})
		evaluated_response = self.client.get(reverse('learning:assignment-submissions', args=(self.assignment.pk,)))
		self.assertContains(evaluated_response, 'Edit Evaluation')
		self.assertContains(evaluated_response, '95.00/100')

	def test_admin_can_inspect_evaluations(self):
		Evaluation.objects.create(
			submission=self.submission,
			evaluator=self.teacher,
			feedback='Reviewed.',
			score=90,
			status=Evaluation.Status.EVALUATED,
		)
		admin_user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)

		response = self.client.get(reverse('admin:learning_evaluation_changelist'))
		self.assertEqual(response.status_code, 200)


class ReviewWorkflowTests(TestCase):
	def setUp(self):
		self.learner = User.objects.create_user(username='review-learner', password='Strong-pass-2026!')
		self.teacher = User.objects.create_user(username='review-teacher', password='Strong-pass-2026!')
		self.outsider = User.objects.create_user(username='review-outsider', password='Strong-pass-2026!')
		self.learner_profile = self.learner.student_profile
		self.teacher_profile = self.teacher.student_profile
		self.python = Skill.objects.create(name='Review Python', category=Skill.Category.PROGRAMMING)
		self.match = Match.objects.create(
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': self.python.name}],
				'student_two_learns_from_one': [],
			},
		)
		self.partnership = LearningPartnership.objects.create(
			match=self.match,
			student_one=self.learner_profile,
			student_two=self.teacher_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=self.learner_profile,
		)
		self.direction = LearningDirection.objects.create(
			partnership=self.partnership,
			teacher=self.teacher_profile,
			learner=self.learner_profile,
			skill=self.python,
		)

	def add_session(self, *, status=LearningSession.Status.SCHEDULED, direction=None, teacher=None):
		start = timezone.now() - timedelta(hours=2)
		return LearningSession.objects.create(
			learning_direction=direction or self.direction,
			title='Python review session',
			scheduled_start=start,
			scheduled_end=start + timedelta(minutes=45),
			status=status,
			created_by=teacher or self.teacher,
		)

	def submit_review(self, *, direction=None, reviewer=None, rating=5, comment='Helpful teaching.'):
		direction = direction or self.direction
		return self.client.post(
			reverse('learning:review-add', args=(direction.pk,)),
			{'rating': rating, 'comment': comment},
		)

	def test_review_model_rejects_ratings_outside_one_to_five(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		for rating in (0, 6):
			with self.subTest(rating=rating):
				review = Review(
					learning_direction=self.direction,
					reviewer=self.learner_profile,
					reviewee=self.teacher_profile,
					rating=rating,
				)
				with self.assertRaises(ValidationError):
					review.full_clean()

	def test_review_model_rejects_comments_over_1000_characters(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		review = Review(
			learning_direction=self.direction,
			reviewer=self.learner_profile,
			reviewee=self.teacher_profile,
			rating=5,
			comment='x' * 1001,
		)
		with self.assertRaises(ValidationError):
			review.full_clean()

	def test_review_model_rejects_reviewer_or_reviewee_outside_direction(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		review = Review(
			learning_direction=self.direction,
			reviewer=self.teacher_profile,
			reviewee=self.learner_profile,
			rating=5,
		)
		with self.assertRaises(ValidationError):
			review.full_clean()

	def test_learner_can_review_after_a_completed_session_and_teacher_is_notified(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		self.client.force_login(self.learner)

		response = self.submit_review(rating=4, comment='Clear examples.')

		self.assertRedirects(response, reverse('learning:directions'))
		review = Review.objects.get(learning_direction=self.direction)
		self.assertEqual(review.reviewer, self.learner_profile)
		self.assertEqual(review.reviewee, self.teacher_profile)
		self.assertEqual(review.rating, 4)
		notification = Notification.objects.get(recipient=self.teacher)
		self.assertEqual(notification.notification_type, Notification.NotificationType.REVIEW_RECEIVED)
		self.assertEqual(notification.related_url, reverse('profile-detail'))

	def test_review_is_not_allowed_before_any_completed_session(self):
		self.client.force_login(self.learner)
		response = self.client.get(reverse('learning:review-add', args=(self.direction.pk,)))
		self.assertRedirects(response, reverse('learning:directions'))
		self.assertFalse(Review.objects.exists())

	def test_cancelled_session_does_not_make_learner_eligible(self):
		self.add_session(status=LearningSession.Status.CANCELLED)
		self.client.force_login(self.learner)
		response = self.client.get(reverse('learning:review-add', args=(self.direction.pk,)))
		self.assertRedirects(response, reverse('learning:directions'))
		self.assertFalse(Review.objects.exists())

	def test_scheduled_session_does_not_make_learner_eligible(self):
		self.add_session(status=LearningSession.Status.SCHEDULED)
		with self.assertRaises(ValidationError):
			create_review(self.direction.pk, self.learner, rating=5, comment='')
		self.assertFalse(Review.objects.exists())

	def test_teacher_cannot_review_themselves(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		with self.assertRaises(PermissionDenied):
			create_review(self.direction.pk, self.teacher, rating=5, comment='')

	def test_unrelated_student_cannot_create_or_access_a_review(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		with self.assertRaises(PermissionDenied):
			create_review(self.direction.pk, self.outsider, rating=5, comment='')
		self.client.force_login(self.outsider)
		response = self.client.get(reverse('learning:review-add', args=(self.direction.pk,)))
		self.assertEqual(response.status_code, 404)
		self.assertFalse(Review.objects.exists())

	def test_duplicate_review_is_rejected(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		create_review(self.direction.pk, self.learner, rating=5, comment='')
		with self.assertRaises(ValidationError):
			create_review(self.direction.pk, self.learner, rating=4, comment='')
		self.assertEqual(Review.objects.filter(learning_direction=self.direction).count(), 1)

	def test_reviewer_can_edit_their_own_review(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		review = create_review(self.direction.pk, self.learner, rating=3, comment='Original')
		self.client.force_login(self.learner)

		response = self.client.post(
			reverse('learning:review-edit', args=(review.pk,)),
			{'rating': 5, 'comment': 'Updated feedback.'},
		)

		self.assertRedirects(response, reverse('learning:directions'))
		review.refresh_from_db()
		self.assertEqual((review.rating, review.comment), (5, 'Updated feedback.'))
		self.assertEqual(Notification.objects.filter(recipient=self.teacher).count(), 1)

	def test_reviewer_can_delete_their_own_review(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		review = create_review(self.direction.pk, self.learner, rating=5, comment='')
		self.client.force_login(self.learner)

		response = self.client.post(reverse('learning:review-delete', args=(review.pk,)))

		self.assertRedirects(response, reverse('learning:directions'))
		self.assertFalse(Review.objects.filter(pk=review.pk).exists())

	def test_reviewee_cannot_edit_another_students_review(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		review = create_review(self.direction.pk, self.learner, rating=5, comment='Original')
		self.client.force_login(self.teacher)

		response = self.client.post(
			reverse('learning:review-edit', args=(review.pk,)),
			{'rating': 1, 'comment': 'Changed by teacher.'},
		)

		self.assertEqual(response.status_code, 404)
		review.refresh_from_db()
		self.assertEqual((review.rating, review.comment), (5, 'Original'))

	def test_student_rating_summary_is_calculated_from_received_reviews(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		create_review(self.direction.pk, self.learner, rating=5, comment='')
		second_learner = User.objects.create_user(username='review-learner-two', password='Strong-pass-2026!')
		second_profile = second_learner.student_profile
		second_match = Match.objects.create(
			student_one=self.teacher_profile,
			student_two=second_profile,
			compatibility_score=75,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [],
				'student_two_learns_from_one': [{'skill_id': self.python.pk, 'skill': self.python.name}],
			},
		)
		second_partnership = LearningPartnership.objects.create(
			match=second_match,
			student_one=self.teacher_profile,
			student_two=second_profile,
			relationship_type=Match.MatchType.ONE_WAY_LEARNING,
			primary_teacher=self.teacher_profile,
			primary_learner=second_profile,
		)
		second_direction = LearningDirection.objects.create(
			partnership=second_partnership,
			teacher=self.teacher_profile,
			learner=second_profile,
			skill=self.python,
		)
		self.add_session(
			status=LearningSession.Status.COMPLETED,
			direction=second_direction,
		)
		create_review(second_direction.pk, second_learner, rating=4, comment='')
		self.client.force_login(self.teacher)

		response = self.client.get(reverse('profile-detail'))

		self.assertEqual(response.context['review_count'], 2)
		self.assertEqual(response.context['rating_average'], Decimal('4.5'))
		self.assertContains(response, 'Review Python')
		self.assertContains(response, 'review-learner-two')

	def test_match_profile_shows_real_teacher_rating_and_review_context(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		create_review(self.direction.pk, self.learner, rating=4, comment='Patient explanations.')
		self.client.force_login(self.learner)

		response = self.client.get(reverse('matching:detail', args=(self.match.pk,)))

		self.assertContains(response, '4.0 / 5')
		self.assertContains(response, 'Patient explanations.')
		self.assertContains(response, 'Review Python')

	def test_one_way_learning_direction_accepts_learner_review_after_completion(self):
		self.add_session(status=LearningSession.Status.COMPLETED)

		review = create_review(self.direction.pk, self.learner, rating=5, comment='Great one-way learning.')

		self.assertEqual(review.learning_direction.partnership, self.partnership)
		self.assertEqual(review.reviewee, self.teacher_profile)
		self.assertEqual(review.reviewer, self.learner_profile)

	def test_learning_workspace_shows_review_action_only_after_completion(self):
		self.client.force_login(self.learner)
		response = self.client.get(reverse('learning:directions'))
		self.assertNotContains(response, 'Review teacher')

		self.add_session(status=LearningSession.Status.COMPLETED)
		response = self.client.get(reverse('learning:directions'))

		self.assertContains(response, 'Review teacher')
		self.assertContains(response, reverse('learning:review-add', args=(self.direction.pk,)))

	def test_partnership_page_exposes_direction_learning_content_and_review_action(self):
		plan = LearningPlan.objects.create(
			learning_direction=self.direction,
			title='One-way Python plan',
			created_by=self.teacher,
			status=LearningPlan.Status.ACTIVE,
		)
		lesson = Lesson.objects.create(learning_plan=plan, title='Variables', order=1)
		Assignment.objects.create(
			lesson=lesson,
			title='Variable practice',
			instructions='Use a variable.',
			created_by=self.teacher,
			status=Assignment.Status.ACTIVE,
		)
		self.add_session(status=LearningSession.Status.COMPLETED)
		self.client.force_login(self.learner)

		response = self.client.get(reverse('matching:partnerships'))

		self.assertContains(response, 'One-way Python plan')
		self.assertContains(response, 'Variable practice')
		self.assertContains(response, 'Python review session')
		self.assertContains(response, 'Review teacher')

	def test_direct_exchange_keeps_separate_reviews_for_both_learning_directions(self):
		student_a = User.objects.create_user(username='direct-review-a', password='Strong-pass-2026!')
		student_b = User.objects.create_user(username='direct-review-b', password='Strong-pass-2026!')
		profile_a = student_a.student_profile
		profile_b = student_b.student_profile
		excel = Skill.objects.create(name='Review Excel', category=Skill.Category.OFFICE_TOOLS)
		python = Skill.objects.create(name='Direct Review Python', category=Skill.Category.PROGRAMMING)
		OfferedSkill.objects.create(profile=profile_a, skill=excel, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=profile_b, skill=excel, learning_level='BEGINNER')
		OfferedSkill.objects.create(profile=profile_b, skill=python, proficiency='ADVANCED')
		LearningSkill.objects.create(profile=profile_a, skill=python, learning_level='BEGINNER')
		match = Match.objects.create(
			student_one=profile_a,
			student_two=profile_b,
			compatibility_score=100,
			match_type=Match.MatchType.DIRECT_EXCHANGE,
			status=Match.Status.ACCEPTED,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': python.pk, 'skill': python.name}],
				'student_two_learns_from_one': [{'skill_id': excel.pk, 'skill': excel.name}],
			},
		)
		partnership = LearningPartnership.objects.create(
			match=match,
			student_one=profile_a,
			student_two=profile_b,
			relationship_type=Match.MatchType.DIRECT_EXCHANGE,
		)
		directions = create_directions_for_partnership(partnership)
		self.assertEqual(len(directions), 2)

		for direction in directions:
			self.add_session(
				status=LearningSession.Status.COMPLETED,
				direction=direction,
				teacher=direction.teacher.user,
			)
		reviews = [
			create_review(direction.pk, direction.learner.user, rating=5, comment='')
			for direction in directions
		]

		self.assertEqual({review.learning_direction_id for review in reviews}, {direction.pk for direction in directions})
		self.assertEqual({review.reviewer_id for review in reviews}, {profile_a.pk, profile_b.pk})
		self.assertEqual({review.reviewee_id for review in reviews}, {profile_a.pk, profile_b.pk})
		self.assertEqual({review.learning_direction.skill_id for review in reviews}, {excel.pk, python.pk})

	def test_admin_can_view_reviews_for_moderation(self):
		self.add_session(status=LearningSession.Status.COMPLETED)
		create_review(self.direction.pk, self.learner, rating=5, comment='')
		admin_user = User.objects.create_superuser(
			username='review-admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)

		response = self.client.get(reverse('admin:learning_review_changelist'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Review Python')

# Create your tests here.
