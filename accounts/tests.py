from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Notification


User = get_user_model()


class AuthenticationTests(TestCase):
	def test_public_pages_render_and_student_cannot_access_admin(self):
		self.assertEqual(self.client.get(reverse('home')).status_code, 200)
		self.assertEqual(self.client.get(reverse('register')).status_code, 200)
		login_response = self.client.get(reverse('login'))
		self.assertEqual(login_response.status_code, 200)
		self.assertNotContains(login_response, 'Admin Login')

		student = User.objects.create_user(username='student-one', password='Strong-pass-2026!')
		self.client.force_login(student)

		response = self.client.get(reverse('admin:index'))

		self.assertEqual(response.status_code, 302)

	def test_authenticated_student_shell_uses_existing_routes(self):
		student = User.objects.create_user(username='shell-student', password='Strong-pass-2026!')
		self.client.force_login(student)

		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'student-dashboard-body')
		self.assertContains(response, '/static/css/layout.css?v=20261005-2')
		self.assertContains(response, 'Welcome back,')
		self.assertContains(response, 'shell-student')
		self.assertContains(response, '/static/css/student-dashboard.css?v=20261005-5')
		self.assertNotContains(response, 'student-profile-progress')
		self.assertNotContains(response, 'Complete profile')
		self.assertContains(response, 'Skill partners')
		self.assertContains(response, 'Upcoming sessions')
		for label in ('Dashboard', 'Discover', 'My Skills', 'Matches &amp; requests', 'Partnerships', 'Learning', 'Sessions', 'Messages', 'Notifications', 'Profile', 'Log out'):
			with self.subTest(label=label):
				self.assertContains(response, label)
		self.assertContains(response, f'href="{reverse("matching:index")}"')
		self.assertContains(response, f'href="{reverse("skills:index")}"')
		self.assertContains(response, f'href="{reverse("matching:partnerships")}"')
		self.assertContains(response, f'href="{reverse("learning:directions")}"')
		self.assertContains(response, f'href="{reverse("learning:sessions")}"')
		self.assertContains(response, f'href="{reverse("chat:chat-list")}"')
		self.assertContains(response, f'href="{reverse("notifications")}"')
		self.assertContains(response, 'data-menu-toggle')
		self.assertContains(response, 'aria-current="page"')

	def test_registration_creates_student_with_hashed_password(self):
		response = self.client.post(reverse('register'), {
			'username': 'student-one',
			'email': 'student@example.com',
			'password1': 'Strong-pass-2026!',
			'password2': 'Strong-pass-2026!',
		})

		self.assertRedirects(response, reverse('login'))
		user = User.objects.get(username='student-one')
		self.assertEqual(user.role, User.Role.STUDENT)
		self.assertNotEqual(user.password, 'Strong-pass-2026!')
		self.assertTrue(user.check_password('Strong-pass-2026!'))

	def test_login_and_logout(self):
		User.objects.create_user(username='student-one', password='Strong-pass-2026!')

		response = self.client.post(reverse('login'), {
			'username': 'student-one',
			'password': 'Strong-pass-2026!',
		})

		self.assertRedirects(response, reverse('home'))
		self.assertTrue(response.wsgi_request.user.is_authenticated)
		response = self.client.post(reverse('logout'))
		self.assertRedirects(response, reverse('home'))

	def test_superuser_is_assigned_admin_role(self):
		admin_user = User.objects.create_superuser(
			username='admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)

		self.assertEqual(admin_user.role, User.Role.ADMIN)
		self.assertTrue(admin_user.is_staff)


class NotificationTests(TestCase):
	def setUp(self):
		self.student = User.objects.create_user(
			username='notification-student',
			password='Strong-pass-2026!',
		)
		self.other_student = User.objects.create_user(
			username='other-notification-student',
			password='Strong-pass-2026!',
		)

	def create_notification(self, recipient, **kwargs):
		defaults = {
			'notification_type': Notification.NotificationType.MATCH_REQUEST,
			'title': 'New match request',
			'message': 'A student wants to connect.',
			'related_url': '/notifications/',
		}
		defaults.update(kwargs)
		return Notification.objects.create(recipient=recipient, **defaults)

	def test_notification_list_is_scoped_to_the_logged_in_student(self):
		own_notification = self.create_notification(self.student)
		self.create_notification(self.other_student, title='Private notification')
		self.client.force_login(self.student)

		response = self.client.get(reverse('notifications'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/static/css/notifications.css?v=20261005-1')
		self.assertContains(response, own_notification.title)
		self.assertContains(response, own_notification.message)
		self.assertContains(response, reverse('notification-open', args=(own_notification.pk,)))
		self.assertContains(response, reverse('notification-read', args=(own_notification.pk,)))
		self.assertContains(response, reverse('notifications-mark-all-read'))
		self.assertNotContains(response, 'Private notification')

	def test_notification_page_requires_an_authenticated_student(self):
		response = self.client.get(reverse('notifications'))
		self.assertEqual(response.status_code, 302)
		self.assertIn(reverse('login'), response.url)

		admin_user = User.objects.create_superuser(
			username='notification-page-admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.client.force_login(admin_user)
		self.assertEqual(self.client.get(reverse('notifications')).status_code, 403)

	def test_student_can_mark_one_notification_as_read(self):
		notification = self.create_notification(self.student)
		self.client.force_login(self.student)

		response = self.client.post(reverse('notification-read', args=(notification.pk,)))

		self.assertRedirects(response, reverse('notifications'))
		notification.refresh_from_db()
		self.assertTrue(notification.is_read)
		self.assertIsNotNone(notification.read_at)

	def test_student_cannot_read_another_students_notification(self):
		notification = self.create_notification(self.other_student)
		self.client.force_login(self.student)

		response = self.client.post(reverse('notification-read', args=(notification.pk,)))

		self.assertEqual(response.status_code, 404)
		notification.refresh_from_db()
		self.assertFalse(notification.is_read)
		self.assertIsNone(notification.read_at)

	def test_mark_all_as_read_only_updates_the_logged_in_students_notifications(self):
		own_notification = self.create_notification(self.student)
		other_notification = self.create_notification(self.other_student)
		self.client.force_login(self.student)

		response = self.client.post(reverse('notifications-mark-all-read'))

		self.assertRedirects(response, reverse('notifications'))
		own_notification.refresh_from_db()
		other_notification.refresh_from_db()
		self.assertTrue(own_notification.is_read)
		self.assertIsNotNone(own_notification.read_at)
		self.assertFalse(other_notification.is_read)
		self.assertIsNone(other_notification.read_at)

	def test_opening_notification_marks_it_read_and_redirects_to_its_local_url(self):
		notification = self.create_notification(self.student, related_url='/notifications/?page=2')
		self.client.force_login(self.student)

		response = self.client.get(reverse('notification-open', args=(notification.pk,)))

		self.assertRedirects(response, '/notifications/?page=2', fetch_redirect_response=False)
		notification.refresh_from_db()
		self.assertTrue(notification.is_read)
		self.assertIsNotNone(notification.read_at)

	def test_external_notification_url_is_rejected_without_marking_it_read(self):
		notification = self.create_notification(self.student, related_url='https://example.com/')
		self.client.force_login(self.student)

		response = self.client.get(reverse('notification-open', args=(notification.pk,)))

		self.assertRedirects(response, reverse('notifications'))
		notification.refresh_from_db()
		self.assertFalse(notification.is_read)

	def test_notification_badge_uses_unread_database_count_and_hides_zero(self):
		self.client.force_login(self.student)
		response = self.client.get(reverse('home'))
		self.assertNotContains(response, 'badge text-bg-danger')

		self.create_notification(self.student)
		self.create_notification(self.student, is_read=True)
		response = self.client.get(reverse('home'))

		self.assertContains(response, 'badge text-bg-danger')
		self.assertContains(response, '>1</span>')

	def test_admin_can_inspect_notifications_without_editing_sensitive_fields(self):
		admin_user = User.objects.create_superuser(
			username='notification-admin',
			email='admin@example.com',
			password='Strong-pass-2026!',
		)
		self.create_notification(self.student)
		self.client.force_login(admin_user)

		response = self.client.get(reverse('admin:accounts_notification_changelist'))
		change_response = self.client.get(
			reverse('admin:accounts_notification_change', args=(Notification.objects.first().pk,))
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(change_response.status_code, 200)
		self.assertNotContains(change_response, 'name="related_url"')
