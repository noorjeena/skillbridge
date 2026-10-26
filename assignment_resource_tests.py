from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from matching.models import LearningPartnership, Match
from skills.models import LearningSkill, OfferedSkill, Skill

from learning.models import Assignment, LearningDirection, LearningPlan, Lesson

User = get_user_model()


class AssignmentResourceTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher-resource', password='Strong-pass-2026!')
        self.learner = User.objects.create_user(username='learner-resource', password='Strong-pass-2026!')
        self.outsider = User.objects.create_user(username='outsider-resource', password='Strong-pass-2026!')
        self.teacher_profile = self.teacher.student_profile
        self.learner_profile = self.learner.student_profile
        self.python = Skill.objects.get_or_create(name='Python', defaults={'category': Skill.Category.PROGRAMMING})[0]

        OfferedSkill.objects.create(profile=self.teacher_profile, skill=self.python, proficiency='ADVANCED')
        LearningSkill.objects.create(profile=self.learner_profile, skill=self.python, learning_level='BEGINNER')

        lower_profile, higher_profile = sorted(
            (self.learner_profile, self.teacher_profile),
            key=lambda profile: profile.pk,
        )
        match = Match.objects.create(
            student_one=lower_profile,
            student_two=higher_profile,
            compatibility_score=90,
            match_type=Match.MatchType.ONE_WAY_LEARNING,
            status=Match.Status.ACCEPTED,
            matched_skills={
                'student_one_learns_from_two': [{'skill_id': self.python.pk, 'skill': self.python.name}],
                'student_two_learns_from_one': [],
            },
        )
        self.partnership = LearningPartnership.objects.create(
            match=match,
            student_one=lower_profile,
            student_two=higher_profile,
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
            title='Python Foundations',
            created_by=self.teacher,
            status=LearningPlan.Status.ACTIVE,
        )
        self.lesson = Lesson.objects.create(learning_plan=self.plan, title='Functions', order=1)

    def create_assignment(self, **kwargs):
        return Assignment.objects.create(
            lesson=self.lesson,
            title='Python Functions Practice',
            instructions='Write a Python function.',
            created_by=self.teacher,
            status=Assignment.Status.ACTIVE,
            **kwargs,
        )

    def test_teacher_can_upload_assignment_resource(self):
        assignment = self.create_assignment()
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.teacher)
                upload = SimpleUploadedFile('python-functions.pdf', b'%PDF-1.4 sample', content_type='application/pdf')
                response = self.client.post(
                    reverse('learning:assignment-edit', args=(assignment.pk,)),
                    {
                        'title': assignment.title,
                        'instructions': assignment.instructions,
                        'status': Assignment.Status.ACTIVE,
                        'resource_file': upload,
                    },
                )
                assignment.refresh_from_db()
                self.assertRedirects(response, reverse('learning:assignment-detail', args=(assignment.pk,)))
                self.assertTrue(Path(media_root, assignment.resource_file.name).is_file())

    def test_invalid_assignment_resource_is_rejected(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('learning:assignment-add', args=(self.lesson.pk,)),
            {
                'title': 'Invalid Resource',
                'instructions': 'Use a real file.',
                'status': Assignment.Status.ACTIVE,
                'resource_file': SimpleUploadedFile('hack.exe', b'not supported', content_type='application/octet-stream'),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('resource_file', response.context['form'].errors)
        self.assertFalse(Assignment.objects.filter(title='Invalid Resource').exists())

    def test_assignment_resource_larger_than_20mb_is_rejected(self):
        self.client.force_login(self.teacher)
        too_large = SimpleUploadedFile('large.pdf', b'a' * (21 * 1024 * 1024), content_type='application/pdf')
        response = self.client.post(
            reverse('learning:assignment-add', args=(self.lesson.pk,)),
            {
                'title': 'Too Large',
                'instructions': 'The file is too large.',
                'status': Assignment.Status.ACTIVE,
                'resource_file': too_large,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('resource_file', response.context['form'].errors)
        self.assertFalse(Assignment.objects.filter(title='Too Large').exists())

    def test_authorized_learner_can_access_assignment_resource_and_unauthorized_student_cannot(self):
        assignment = self.create_assignment()
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                upload = SimpleUploadedFile('assignment.pdf', b'%PDF-1.4 assignment', content_type='application/pdf')
                assignment.resource_file.save('assignment.pdf', upload)
                assignment.save()

                self.client.force_login(self.learner)
                detail_response = self.client.get(reverse('learning:assignment-detail', args=(assignment.pk,)))
                resource_response = self.client.get(reverse('learning:assignment-resource-file', args=(assignment.pk,)))
                self.assertEqual(detail_response.status_code, 200)
                self.assertContains(detail_response, 'Assignment Resource')
                self.assertEqual(resource_response.status_code, 200)
                self.assertEqual(b''.join(resource_response.streaming_content), b'%PDF-1.4 assignment')

                self.client.force_login(self.outsider)
                self.assertEqual(self.client.get(reverse('learning:assignment-resource-file', args=(assignment.pk,))).status_code, 404)
