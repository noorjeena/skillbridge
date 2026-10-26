from .models import User
from .services import get_unread_count


def notification_count(request):
    if request.user.is_authenticated and request.user.role == User.Role.STUDENT:
        return {'unread_notification_count': get_unread_count(request.user)}
    return {'unread_notification_count': 0}
