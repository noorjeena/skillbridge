from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from matching.models import Match
from skills.models import OfferedSkill, Skill


User = get_user_model()


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='dashboard-admin',
            email='admin@example.com',
            password='Strong-pass-2026!',
        )
        self.student = User.objects.create_user(
            username='dashboard-student',
            password='Strong-pass-2026!',
        )

    def test_anonymous_dashboard_access_uses_admin_login(self):
        response = self.client.get(reverse('admin_dashboard:overview'))

        self.assertRedirects(
            response,
            f'{reverse("admin-login")}?next={reverse("admin_dashboard:overview")}',
        )

    def test_dashboard_routes_are_admin_only(self):
        routes = (
            'admin_dashboard:overview',
            'admin_dashboard:users',
            'admin_dashboard:skills',
            'admin_dashboard:matches',
            'admin_dashboard:partnerships',
            'admin_dashboard:sessions',
            'admin_dashboard:assignments',
            'admin_dashboard:reviews',
            'admin_dashboard:messages',
            'admin_dashboard:notifications',
        )
        self.client.force_login(self.student)

        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_admin_login_redirects_admin_to_custom_dashboard(self):
        response = self.client.post(reverse('admin-login'), {
            'username': self.admin.username,
            'password': 'Strong-pass-2026!',
        })

        self.assertRedirects(response, reverse('admin_dashboard:overview'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_admin_login_page_has_no_public_navigation(self):
        response = self.client.get(reverse('admin-login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Login')
        self.assertContains(response, 'Administration Portal')
        self.assertNotContains(response, 'public-header')
        self.assertNotContains(response, 'Back to Student Login')
        self.assertNotContains(response, 'Create account')

    def test_student_login_keeps_student_destination_even_from_admin_login(self):
        response = self.client.post(reverse('admin-login'), {
            'username': self.student.username,
            'password': 'Strong-pass-2026!',
        })

        self.assertRedirects(response, reverse('home'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_student_cannot_use_admin_dashboard_as_login_next_target(self):
        response = self.client.post(
            f'{reverse("login")}?next={reverse("admin_dashboard:overview")}',
            {
                'username': self.student.username,
                'password': 'Strong-pass-2026!',
                'next': reverse('admin_dashboard:overview'),
            },
        )

        self.assertRedirects(response, reverse('home'))

    def test_admin_can_render_dashboard_and_monitoring_pages(self):
        self.client.force_login(self.admin)
        routes = (
            'admin_dashboard:overview',
            'admin_dashboard:users',
            'admin_dashboard:skills',
            'admin_dashboard:matches',
            'admin_dashboard:partnerships',
            'admin_dashboard:sessions',
            'admin_dashboard:assignments',
            'admin_dashboard:reviews',
            'admin_dashboard:messages',
            'admin_dashboard:notifications',
        )

        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)

    def test_django_admin_remains_available_to_staff_and_superusers(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)

    def test_admin_logout_uses_existing_logout_route(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_navigation_links_to_django_system_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_dashboard:overview'))

        self.assertContains(response, 'SkillBridge')
        self.assertContains(response, 'Admin')
        self.assertContains(response, 'System Admin')
        self.assertContains(response, f'href="{reverse("admin:index")}"')

    def test_admin_can_create_and_deactivate_catalogue_skill(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_dashboard:skill-add'), {
            'name': '  Admin   Dashboard Regression Skill ',
            'category': Skill.Category.OTHER,
            'description': 'Working with data',
            'is_active': 'on',
        })

        self.assertRedirects(response, reverse('admin_dashboard:skills'))
        skill = Skill.objects.get(name='Admin Dashboard Regression Skill')
        self.assertTrue(skill.is_active)

        response = self.client.post(
            reverse('admin_dashboard:skill-toggle', args=(skill.pk,)),
        )

        self.assertRedirects(response, reverse('admin_dashboard:skills'))
        skill.refresh_from_db()
        self.assertFalse(skill.is_active)

    def test_admin_can_delete_unused_catalogue_skill(self):
        skill = Skill.objects.create(
            name='Unused admin test skill',
            category=Skill.Category.OTHER,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )

        self.assertRedirects(response, reverse('admin_dashboard:skills'))
        self.assertFalse(Skill.objects.filter(pk=skill.pk).exists())

    def test_admin_cannot_delete_skill_used_by_a_student(self):
        skill = Skill.objects.create(name='Protected student skill')
        OfferedSkill.objects.create(
            profile=self.student.student_profile,
            skill=skill,
            proficiency=OfferedSkill.Proficiency.BEGINNER,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )

        self.assertRedirects(
            response,
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )
        self.assertTrue(Skill.objects.filter(pk=skill.pk).exists())

    def test_admin_cannot_delete_skill_referenced_by_historical_match(self):
        skill = Skill.objects.create(name='Historical match skill')
        other_student = User.objects.create_user(
            username='dashboard-other-student',
            password='Strong-pass-2026!',
        )
        profiles = sorted(
            (self.student.student_profile, other_student.student_profile),
            key=lambda profile: profile.pk,
        )
        Match.objects.create(
            student_one=profiles[0],
            student_two=profiles[1],
            compatibility_score=80,
            match_type=Match.MatchType.DIRECT_EXCHANGE,
            matched_skills={
                'student_one_learns_from_two': [
                    {'skill_id': skill.pk, 'skill': skill.name},
                ],
                'student_two_learns_from_one': [],
            },
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )

        self.assertRedirects(
            response,
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )
        self.assertTrue(Skill.objects.filter(pk=skill.pk).exists())

    def test_student_cannot_manage_catalogue_skills(self):
        skill = Skill.objects.create(name='Student restricted skill')
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('admin_dashboard:skill-delete', args=(skill.pk,)),
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Skill.objects.filter(pk=skill.pk).exists())
