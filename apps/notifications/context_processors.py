from .services import unread_count


def unread_notifications(request):
    """Unread inbox count for the navigation badge."""
    if not request.user.is_authenticated:
        return {}
    return {'unread_notification_count': unread_count(request.user)}
