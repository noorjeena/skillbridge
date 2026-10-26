from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Notification


@transaction.atomic
def create_notification(recipient, notification_type, title, message, related_url=None):
    if recipient is None:
        raise ValueError('A recipient is required for a notification.')
    if not title or not title.strip():
        raise ValidationError('Notification title is required.')
    if not message or not message.strip():
        raise ValidationError('Notification message is required.')
    if notification_type not in dict(Notification.NotificationType.choices):
        raise ValidationError('Unsupported notification type.')

    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title.strip(),
        message=message.strip(),
        related_url=related_url or '',
    )
    return notification


def mark_as_read(notification):
    if notification.is_read:
        return notification
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=('is_read', 'read_at'))
    return notification


def mark_all_as_read(user):
    updated = Notification.objects.filter(recipient=user, is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
    return updated


def get_unread_count(user):
    return Notification.objects.filter(recipient=user, is_read=False).count()


def get_notifications(user):
    return Notification.objects.filter(recipient=user).select_related('recipient')
