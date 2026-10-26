from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class SkillBridgeUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', self.model.Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', 'Student'
        ADMIN = 'ADMIN', 'Admin'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)

    objects = SkillBridgeUserManager()

    def __str__(self):
        return self.username


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        MATCH_REQUEST = 'MATCH_REQUEST', 'Match Request'
        MATCH_ACCEPTED = 'MATCH_ACCEPTED', 'Match Accepted'
        MATCH_REJECTED = 'MATCH_REJECTED', 'Match Rejected'
        NEW_MESSAGE = 'NEW_MESSAGE', 'New Message'
        ASSIGNMENT_CREATED = 'ASSIGNMENT_CREATED', 'New Assignment'
        ASSIGNMENT_SUBMITTED = 'ASSIGNMENT_SUBMITTED', 'Assignment Submitted'
        ASSIGNMENT_EVALUATED = 'ASSIGNMENT_EVALUATED', 'Assignment Evaluated'
        SESSION_SCHEDULED = 'SESSION_SCHEDULED', 'New Learning Session'
        SESSION_UPDATED = 'SESSION_UPDATED', 'Session Updated'
        SESSION_CANCELLED = 'SESSION_CANCELLED', 'Session Cancelled'
        SESSION_COMPLETED = 'SESSION_COMPLETED', 'Session Completed'
        REVIEW_RECEIVED = 'REVIEW_RECEIVED', 'New Learning Partner Review'

    recipient = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=300)
    related_url = models.CharField(max_length=500, blank=True, default='')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', 'pk')
        indexes = [
            models.Index(fields=('recipient', 'is_read', 'created_at')),
        ]

    def __str__(self):
        return f'{self.title} ({self.recipient})'
