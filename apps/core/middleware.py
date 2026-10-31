from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class UserTimezoneMiddleware:
    """Render times in the signed-in user's own time zone; everyone else sees the server's TIME_ZONE."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        name = getattr(request.user, 'time_zone', '') if request.user.is_authenticated else ''
        try:
            if name:
                timezone.activate(ZoneInfo(name))
            else:
                timezone.deactivate()
        except (ZoneInfoNotFoundError, ValueError):
            timezone.deactivate()
        return self.get_response(request)
