from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Notification
from profiles.models import StudentProfile
from skills.models import LearningSkill, OfferedSkill, Skill

from .models import Conversation, LearningPartnership, Match, MatchRequest
from .services import calculate_match, get_or_create_match, send_message


User = get_user_model()


class MatchingTestDataMixin:
	def setUp(self):
		self.student_a = User.objects.create_user(username='student-a', password='Strong-pass-2026!')
		self.student_b = User.objects.create_user(username='student-b', password='Strong-pass-2026!')
		self.student_c = User.objects.create_user(username='student-c', password='Strong-pass-2026!')
		self.profile_a = StudentProfile.objects.get(user=self.student_a)
		self.profile_b = StudentProfile.objects.get(user=self.student_b)
		self.profile_c = StudentProfile.objects.get(user=self.student_c)
		self.python, _ = Skill.objects.get_or_create(
			name='Python',
			defaults={'category': Skill.Category.PROGRAMMING},
		)
		self.excel, _ = Skill.objects.get_or_create(
			name='Excel',
			defaults={'category': Skill.Category.OFFICE_TOOLS},
		)
		self.django, _ = Skill.objects.get_or_create(
			name='Django',
			defaults={'category': Skill.Category.WEB_DEVELOPMENT},
		)

	def add_offer(self, profile, skill, proficiency='ADVANCED'):
		return OfferedSkill.objects.create(profile=profile, skill=skill, proficiency=proficiency)

	def add_learning(self, profile, skill, level='BEGINNER'):
		return LearningSkill.objects.create(profile=profile, skill=skill, learning_level=level)

	def make_direct_exchange(self):
		self.add_learning(self.profile_a, self.python)
		self.add_offer(self.profile_b, self.python)
		self.add_learning(self.profile_b, self.excel)
		self.add_offer(self.profile_a, self.excel)
		return calculate_match(self.profile_a, self.profile_b)


class MatchingServiceTests(MatchingTestDataMixin, TestCase):
	def test_two_directions_produce_direct_exchange(self):
		calculation = self.make_direct_exchange()

		self.assertEqual(calculation.match_type, Match.MatchType.DIRECT_EXCHANGE)
		if calculation.student_one.pk == self.profile_a.pk:
			self.assertEqual(calculation.matched_skills['student_one_learns_from_two'][0]['skill'], 'Python')
			self.assertEqual(calculation.matched_skills['student_two_learns_from_one'][0]['skill'], 'Excel')
		else:
			self.assertEqual(calculation.matched_skills['student_two_learns_from_one'][0]['skill'], 'Python')
			self.assertEqual(calculation.matched_skills['student_one_learns_from_two'][0]['skill'], 'Excel')

	def test_one_way_learning_is_valid_without_reciprocal_skill(self):
		self.add_learning(self.profile_c, self.python)
		self.add_offer(self.profile_b, self.python)
		self.add_learning(self.profile_b, self.django)
		self.add_offer(self.profile_c, self.excel)

		calculation = calculate_match(self.profile_c, self.profile_b)

		self.assertEqual(calculation.match_type, Match.MatchType.ONE_WAY_LEARNING)
		if calculation.student_one.pk == self.profile_c.pk:
			direction = calculation.matched_skills['student_one_learns_from_two']
			self.assertFalse(calculation.matched_skills['student_two_learns_from_one'])
		else:
			direction = calculation.matched_skills['student_two_learns_from_one']
			self.assertFalse(calculation.matched_skills['student_one_learns_from_two'])
		self.assertEqual(direction[0]['skill'], 'Python')

	def test_no_compatible_direction_returns_no_match(self):
		self.add_learning(self.profile_a, self.python)
		self.add_offer(self.profile_b, self.excel)

		self.assertIsNone(calculate_match(self.profile_a, self.profile_b))

	def test_student_cannot_match_with_themselves(self):
		self.add_learning(self.profile_a, self.python)
		self.add_offer(self.profile_a, self.python)

		self.assertIsNone(calculate_match(self.profile_a, self.profile_a))

	def test_direct_exchange_scores_higher_than_one_way(self):
		direct = self.make_direct_exchange()
		self.add_learning(self.profile_c, self.python)

		one_way = calculate_match(self.profile_c, self.profile_b)

		self.assertGreater(direct.compatibility_score, one_way.compatibility_score)

	def test_score_is_bounded_and_optional_components_can_be_added(self):
		self.add_learning(self.profile_a, self.python, level='ADVANCED')
		self.add_offer(self.profile_b, self.python, proficiency='BEGINNER')

		base = calculate_match(self.profile_a, self.profile_b)
		extended = calculate_match(
			self.profile_a,
			self.profile_b,
			availability_fit=0.8,
			trust_fit=0.9,
		)

		self.assertGreaterEqual(base.compatibility_score, 0)
		self.assertLessEqual(base.compatibility_score, 100)
		self.assertGreaterEqual(extended.compatibility_score, 0)
		self.assertLessEqual(extended.compatibility_score, 100)
		self.assertEqual(extended.score_breakdown['availability']['available_weight'], 15)
		self.assertEqual(extended.score_breakdown['trust']['available_weight'], 10)

	def test_reversed_pair_returns_the_same_database_match(self):
		self.make_direct_exchange()

		first = get_or_create_match(self.profile_a, self.profile_b)
		reversed_pair = get_or_create_match(self.profile_b, self.profile_a)

		self.assertEqual(first.pk, reversed_pair.pk)
		self.assertEqual(Match.objects.count(), 1)


class EmptyMatchDiscoveryTests(MatchingTestDataMixin, TestCase):
	def test_empty_recommendations_show_skill_setup_actions(self):
		self.client.force_login(self.student_a)

		response = self.client.get(reverse('matching:index'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/matching.css?v=20261005-3')
		self.assertContains(response, 'Your skill exchange story starts with you.')
		self.assertContains(response, f'href="{reverse("skills:teach-add")}"')
		self.assertContains(response, f'href="{reverse("skills:learn-add")}"')
		self.assertContains(response, f'href="{reverse("skills:index")}"')


class MatchRequestWorkflowTests(MatchingTestDataMixin, TestCase):
	def setUp(self):
		super().setUp()
		self.make_direct_exchange()
		self.match = get_or_create_match(self.profile_a, self.profile_b)

	def test_match_requests_page_renders_received_actions_and_sent_status(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
			message='Would you like to exchange skills?',
		)
		self.client.force_login(self.student_b)

		received_response = self.client.get(reverse('matching:requests'))

		self.assertEqual(received_response.status_code, 200)
		self.assertContains(received_response, 'Requests received')
		self.assertContains(received_response, self.student_a.username)
		self.assertContains(received_response, 'Would you like to exchange skills?')
		self.assertContains(received_response, 'You can teach')
		self.assertContains(received_response, 'They can teach')
		self.assertContains(
			received_response,
			reverse('matching:respond', args=(match_request.pk, 'accept')),
		)
		self.assertContains(
			received_response,
			reverse('matching:respond', args=(match_request.pk, 'reject')),
		)
		self.assertContains(received_response, 'csrfmiddlewaretoken')

		self.client.force_login(self.student_a)
		sent_response = self.client.get(reverse('matching:requests'))

		self.assertContains(sent_response, 'Requests sent')
		self.assertContains(sent_response, self.student_b.username)
		self.assertContains(sent_response, 'Pending response')
		self.assertContains(
			sent_response,
			reverse('matching:detail', args=(self.match.pk,)),
		)

	def test_student_can_send_match_request(self):
		self.client.force_login(self.student_a)

		response = self.client.post(reverse('matching:request', args=(self.match.pk,)), {
			'message': 'Would you like to exchange skills?'
		})

		self.assertRedirects(response, reverse('matching:requests'))
		match_request = MatchRequest.objects.get(match=self.match)
		self.assertEqual(match_request.sender, self.profile_a)
		self.assertEqual(match_request.receiver, self.profile_b)
		self.assertEqual(match_request.status, MatchRequest.Status.PENDING)
		self.assertEqual(self.match.__class__.objects.get(pk=self.match.pk).status, Match.Status.REQUESTED)
		notification = Notification.objects.get(recipient=self.student_b)
		self.assertEqual(notification.notification_type, Notification.NotificationType.MATCH_REQUEST)

	def test_receiver_acceptance_creates_partnership(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		self.client.force_login(self.student_b)

		response = self.client.post(reverse('matching:respond', args=(match_request.pk, 'accept')))

		self.assertRedirects(response, reverse('matching:requests'))
		match_request.refresh_from_db()
		self.match.refresh_from_db()
		partnership = LearningPartnership.objects.get(match=self.match)
		self.assertEqual(match_request.status, MatchRequest.Status.ACCEPTED)
		self.assertEqual(self.match.status, Match.Status.ACCEPTED)
		self.assertEqual(partnership.relationship_type, Match.MatchType.DIRECT_EXCHANGE)
		self.assertIsNone(partnership.primary_teacher)
		self.assertIsNone(partnership.primary_learner)
		notification = Notification.objects.get(recipient=self.student_a)
		self.assertEqual(notification.notification_type, Notification.NotificationType.MATCH_ACCEPTED)

	def test_accepting_one_way_match_records_teacher_and_learner(self):
		self.add_offer(self.profile_c, self.python)
		one_way_match = Match.objects.create(
			student_one=self.profile_a,
			student_two=self.profile_c,
			compatibility_score=60,
			match_type=Match.MatchType.ONE_WAY_LEARNING,
			matched_skills={
				'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': 'Python'}],
				'student_two_learns_from_one': [],
			},
		)
		match_request = MatchRequest.objects.create(
			match=one_way_match,
			sender=self.profile_a,
			receiver=self.profile_c,
		)

		from matching.services import respond_to_match_request
		partnership = respond_to_match_request(match_request, self.profile_c, accept=True)

		self.assertEqual(partnership.primary_teacher, self.profile_c)
		self.assertEqual(partnership.primary_learner, self.profile_a)

	def test_rejection_does_not_create_partnership(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		self.client.force_login(self.student_b)

		response = self.client.post(reverse('matching:respond', args=(match_request.pk, 'reject')))

		self.assertRedirects(response, reverse('matching:requests'))
		match_request.refresh_from_db()
		self.assertEqual(match_request.status, MatchRequest.Status.REJECTED)
		self.assertFalse(LearningPartnership.objects.filter(match=self.match).exists())
		notification = Notification.objects.get(recipient=self.student_a)
		self.assertEqual(notification.notification_type, Notification.NotificationType.MATCH_REJECTED)

	def test_partnership_message_notifies_the_other_student_once(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		from matching.services import respond_to_match_request
		partnership = respond_to_match_request(match_request, self.profile_b, accept=True)
		conversation = Conversation.objects.get(partnership=partnership)

		message = send_message(conversation, self.student_a, 'Ready to start learning?')

		self.assertEqual(message.content, 'Ready to start learning?')
		notification = Notification.objects.get(recipient=self.student_b)
		self.assertEqual(notification.notification_type, Notification.NotificationType.NEW_MESSAGE)
		self.assertEqual(Notification.objects.filter(recipient=self.student_b).count(), 1)

	def test_student_cannot_respond_to_another_students_request(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		self.client.force_login(self.student_c)

		response = self.client.post(reverse('matching:respond', args=(match_request.pk, 'accept')))

		self.assertEqual(response.status_code, 404)
		match_request.refresh_from_db()
		self.assertEqual(match_request.status, MatchRequest.Status.PENDING)
		self.assertFalse(LearningPartnership.objects.filter(match=self.match).exists())

	def test_student_cannot_send_duplicate_pending_requests(self):
		self.client.force_login(self.student_a)
		request_url = reverse('matching:request', args=(self.match.pk,))

		self.client.post(request_url)
		response = self.client.post(request_url)

		self.assertRedirects(response, reverse('matching:detail', args=(self.match.pk,)))
		self.assertEqual(MatchRequest.objects.filter(match=self.match, status='PENDING').count(), 1)

	def test_rejected_match_can_be_requested_again(self):
		MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
			status=MatchRequest.Status.REJECTED,
		)
		self.match.status = Match.Status.REJECTED
		self.match.save(update_fields=('status', 'updated_at'))
		self.client.force_login(self.student_a)

		response = self.client.post(reverse('matching:request', args=(self.match.pk,)))

		self.assertRedirects(response, reverse('matching:requests'))
		self.assertEqual(MatchRequest.objects.filter(match=self.match, status='PENDING').count(), 1)

	def test_recommendations_render_compatible_profiles_and_directions(self):
		self.client.force_login(self.student_a)

		response = self.client.get(reverse('matching:index'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Recommended Skill Partners')
		self.assertContains(response, self.student_b.username)
		self.assertContains(response, 'Direct Exchange')
		self.assertContains(response, 'Python')
		self.assertContains(response, 'Excel')
		self.assertFalse(Match.objects.filter(student_one=self.profile_a, student_two=self.profile_a).exists())

	def test_match_detail_shows_correct_learning_directions(self):
		self.client.force_login(self.student_a)

		response = self.client.get(reverse('matching:detail', args=(self.match.pk,)))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'You can learn from')
		self.assertContains(response, 'Python')
		self.assertContains(response, 'can learn from you')
		self.assertContains(response, 'Excel')

	def test_only_match_participants_can_view_match_details(self):
		self.client.force_login(self.student_c)

		response = self.client.get(reverse('matching:detail', args=(self.match.pk,)))

		self.assertEqual(response.status_code, 404)

	def test_partnership_is_visible_to_both_students_after_acceptance(self):
		match_request = MatchRequest.objects.create(
			match=self.match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		from matching.services import respond_to_match_request
		respond_to_match_request(match_request, self.profile_b, accept=True)

		for student in (self.student_a, self.student_b):
			with self.subTest(student=student.username):
				self.client.force_login(student)
				response = self.client.get(reverse('matching:partnerships'))
				self.assertContains(response, '/static/css/matching.css?v=20261005-3')
				self.assertContains(response, 'Learning partnerships')
				self.assertContains(response, 'Direct Exchange')
				self.assertContains(response, 'Learning directions')
				self.assertContains(response, reverse('chat:chat-list'))
				self.assertContains(response, reverse('learning:directions'))

	def test_partnerships_empty_state_links_to_match_discovery(self):
		self.client.force_login(self.student_a)

		response = self.client.get(reverse('matching:partnerships'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'No active partnerships yet')
		self.assertContains(response, reverse('matching:index'))

	def test_unauthenticated_users_cannot_view_matching_pages(self):
		self.client.logout()

		for url in (
			reverse('matching:index'),
			reverse('matching:requests'),
			reverse('matching:partnerships'),
			reverse('matching:detail', args=(self.match.pk,)),
		):
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertEqual(response.status_code, 302)
				self.assertIn(reverse('login'), response.url)


class ChatConversationDetailViewTests(MatchingTestDataMixin, TestCase):
	def setUp(self):
		super().setUp()
		self.make_direct_exchange()
		match = get_or_create_match(self.profile_a, self.profile_b)
		match_request = MatchRequest.objects.create(
			match=match,
			sender=self.profile_a,
			receiver=self.profile_b,
		)
		from matching.services import respond_to_match_request
		partnership = respond_to_match_request(match_request, self.profile_b, accept=True)
		self.conversation = Conversation.objects.get(partnership=partnership)

	def test_chat_inbox_renders_conversation_preview_and_unread_state(self):
		send_message(self.conversation, self.student_a, 'Ready to practice Python together?')
		self.client.force_login(self.student_b)

		response = self.client.get(reverse('chat:chat-list'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/chat.css?v=20261005-1')
		self.assertContains(response, 'YOUR LEARNING COMMUNITY')
		self.assertContains(response, self.student_a.username)
		self.assertContains(response, 'Direct Exchange')
		self.assertContains(response, 'Ready to practice Python together?')
		self.assertContains(response, '1 unread')
		self.assertContains(response, reverse('chat:chat-detail', args=(self.conversation.pk,)))

	def test_participant_can_view_chat_conversation(self):
		self.client.force_login(self.student_a)

		response = self.client.get(
			reverse('chat:chat-detail', args=(self.conversation.pk,)),
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Chat with')
		self.assertContains(response, reverse('chat:chat-list'))
		self.assertContains(response, 'chat-thread-card')
		self.assertContains(response, 'chat-send-button')

	def test_nonparticipant_cannot_view_chat_conversation(self):
		self.client.force_login(self.student_c)

		response = self.client.get(
			reverse('chat:chat-detail', args=(self.conversation.pk,)),
		)

		self.assertEqual(response.status_code, 404)


class MatchAdminTests(TestCase):
	def test_admin_can_view_matches(self):
		admin_user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)

		response = self.client.get(reverse('admin:matching_match_changelist'))

		self.assertEqual(response.status_code, 200)

# Create your tests here.
