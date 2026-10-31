"""The events API's rules: payload validation, a fixed-window rate limit per API key, and turning events into
incident changes.

Payload (JSON object):
    event_action  "trigger" | "acknowledge" | "resolve"                     required
    dedup_key     string, at most 255 characters                            required to acknowledge or resolve
    summary       string, at most 255 characters                            required to trigger
    severity      "critical" | "error" | "warning" | "info"                 required to trigger
    details       object of extra context, shown on the incident            optional
"""
from collections import namedtuple
from datetime import UTC, datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.choices import Severity
from apps.incidents import services as incidents
from apps.incidents.models import Incident

from .models import Alert, RateLimitWindow

Action = Alert.Action
Outcome = Alert.Outcome
RateLimit = namedtuple('RateLimit', 'allowed limit remaining retry_after')

MAX_TEXT_LENGTH = 255
MESSAGES = {
    Outcome.TRIGGERED: 'Incident triggered.',
    Outcome.DEDUPLICATED: 'Event grouped into the open incident with this dedup_key.',
    Outcome.ACKNOWLEDGED: 'Incident acknowledged.',
    Outcome.RESOLVED: 'Incident resolved.',
}


class EventError(Exception):
    """An invalid event. `errors` maps each bad field to what is wrong with it."""

    def __init__(self, errors):
        super().__init__('Invalid event.')
        self.errors = errors


# Rate limiting ---------------------------------------------------------------------------------------------------

def check_rate_limit(api_key, now=None):
    """Count this request against the key's current fixed window and say whether it is allowed.

    Windows start at multiples of EVENTS_RATE_LIMIT_WINDOW seconds since the epoch. The counter is incremented with
    a single UPDATE (or created, with a retry if a concurrent request created it first), so it is exact under load.
    """
    now = now or timezone.now()
    limit, window = settings.EVENTS_RATE_LIMIT, settings.EVENTS_RATE_LIMIT_WINDOW
    epoch = int(now.timestamp())
    start_ts = epoch - epoch % window
    window_start = datetime.fromtimestamp(start_ts, tz=UTC)
    counter = RateLimitWindow.objects.filter(api_key=api_key, window_start=window_start)

    if not counter.update(count=F('count') + 1):
        try:
            with transaction.atomic():
                RateLimitWindow.objects.create(api_key=api_key, window_start=window_start, count=1)
        except IntegrityError:
            counter.update(count=F('count') + 1)
        RateLimitWindow.objects.filter(api_key=api_key, window_start__lt=window_start).delete()
    count = counter.values_list('count', flat=True).get()
    retry_after = max(1, start_ts + window - epoch)
    return RateLimit(count <= limit, limit, max(0, limit - count), retry_after)


# Validation ------------------------------------------------------------------------------------------------------

def _text(data, field, errors, required):
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = 'This field is required.'
        return None
    if not isinstance(value, str):
        errors[field] = 'Must be a string.'
        return None
    if len(value) > MAX_TEXT_LENGTH:
        errors[field] = f'Must be at most {MAX_TEXT_LENGTH} characters.'
        return None
    return value.strip()


def validate_event(data):
    """Return the cleaned event as a dict, or raise EventError listing every problem."""
    if not isinstance(data, dict):
        raise EventError({'body': 'Send a JSON object.'})
    errors = {}
    action = data.get('event_action')
    if action not in Action.values:
        errors['event_action'] = f"Must be one of: {', '.join(Action.values)}."
    triggering = action == Action.TRIGGER
    event = {
        'action': action,
        'dedup_key': _text(data, 'dedup_key', errors, required=action in (Action.ACKNOWLEDGE, Action.RESOLVE)),
        'summary': _text(data, 'summary', errors, required=triggering),
        'severity': data.get('severity'),
        'details': {} if data.get('details') is None else data['details'],
    }
    if triggering and event['severity'] not in Severity.values:
        errors['severity'] = f"Must be one of: {', '.join(Severity.values)}."
    if not isinstance(event['details'], dict):
        errors['details'] = 'Must be a JSON object.'
    if errors:
        raise EventError(errors)
    return event


# Processing ------------------------------------------------------------------------------------------------------

def _change(incident, action):
    """Acknowledge or resolve; a move the state machine rejects is reported back, not treated as an error."""
    try:
        if action == Action.ACKNOWLEDGE:
            incidents.acknowledge(incident)
            return Outcome.ACKNOWLEDGED, MESSAGES[Outcome.ACKNOWLEDGED]
        incidents.resolve(incident)
        return Outcome.RESOLVED, MESSAGES[Outcome.RESOLVED]
    except incidents.IncidentError as error:
        return Outcome.IGNORED, str(error)


def process_event(api_key, data):
    """Validate and apply one event for the key's service; returns the JSON response body."""
    event = validate_event(data)
    service = api_key.service
    with transaction.atomic():
        if event['action'] == Action.TRIGGER:
            incident, created = incidents.trigger(
                service, event['summary'], event['severity'], dedup_key=event['dedup_key'],
                details=event['details'], source=Incident.Source.API,
            )
            outcome = Outcome.TRIGGERED if created else Outcome.DEDUPLICATED
            message = MESSAGES[outcome]
        else:
            incident = incidents.find_open(service, event['dedup_key'])
            if incident is None:
                outcome, message = Outcome.IGNORED, 'No open incident has this dedup_key.'
            else:
                outcome, message = _change(incident, event['action'])
        Alert.objects.create(
            service=service, incident=incident, api_key=api_key, action=event['action'], outcome=outcome,
            dedup_key=incident.dedup_key if incident else event['dedup_key'], summary=event['summary'] or '',
            severity=event['severity'] or '', payload=data,
        )
    return {
        'status': 'success',
        'outcome': outcome,
        'message': message,
        'dedup_key': incident.dedup_key if incident else event['dedup_key'],
        'incident_id': incident.pk if incident else None,
        'incident_status': incident.status if incident else None,
    }
