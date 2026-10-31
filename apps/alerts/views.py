import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.services.services import authenticate

from . import services

AUTH_SCHEMES = ('bearer', 'token')


def _error(status, message, headers=None, **extra):
    return JsonResponse({'status': 'error', 'error': message, **extra}, status=status, headers=headers)


def api_key_from_header(request):
    """The key from "Authorization: Bearer <key>" (or "Token <key>"), or None."""
    scheme, _, credentials = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() not in AUTH_SCHEMES:
        return None
    credentials = credentials.strip()
    if credentials.startswith('token='):
        credentials = credentials[len('token='):]
    return credentials or None


@csrf_exempt
def events(request):
    """POST /api/v1/events/: trigger, acknowledge or resolve an incident on the API key's service.

    202 accepted, 400 invalid JSON or event, 401 bad key, 405 not POST, 413 too large, 429 rate limited.
    """
    if request.method != 'POST':
        return _error(405, 'Use POST.', headers={'Allow': 'POST'})
    api_key = authenticate(api_key_from_header(request))
    if api_key is None:
        return _error(401, 'Missing, unknown or revoked API key. Send "Authorization: Bearer <key>".',
                      headers={'WWW-Authenticate': 'Bearer realm="beacon-events"'})

    limit = services.check_rate_limit(api_key)
    headers = {'X-RateLimit-Limit': str(limit.limit), 'X-RateLimit-Remaining': str(limit.remaining)}
    if not limit.allowed:
        headers['Retry-After'] = str(limit.retry_after)
        return _error(429, f'Rate limit exceeded: {limit.limit} requests per {settings.EVENTS_RATE_LIMIT_WINDOW} '
                           f'seconds for this API key. Retry in {limit.retry_after} s.', headers=headers)

    try:
        too_big = int(request.headers.get('Content-Length') or 0) > settings.EVENTS_MAX_BODY_BYTES
    except ValueError:
        too_big = False
    if too_big or len(request.body) > settings.EVENTS_MAX_BODY_BYTES:
        return _error(413, f'Request body is larger than {settings.EVENTS_MAX_BODY_BYTES} bytes.', headers=headers)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _error(400, 'Request body must be valid JSON.', headers=headers)

    try:
        result = services.process_event(api_key, data)
    except services.EventError as error:
        return _error(400, 'Invalid event.', headers=headers, errors=error.errors)
    return JsonResponse(result, status=202, headers=headers)
