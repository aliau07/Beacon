"""Incident lifecycle: triggered -> acknowledged -> resolved, or triggered -> resolved; nothing else.

Every change is written to the incident's timeline, and the matching signal is sent once the transaction commits.
"""
from functools import partial
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.choices import Severity
from apps.teams.services import teams_for

from . import signals
from .models import Incident, TimelineEntry

Status = Incident.Status
Kind = TimelineEntry.Kind

TRANSITIONS = {
    Status.TRIGGERED: (Status.ACKNOWLEDGED, Status.RESOLVED),
    Status.ACKNOWLEDGED: (Status.RESOLVED,),
    Status.RESOLVED: (),
}
SIGNALS = {
    Status.TRIGGERED: signals.incident_triggered,
    Status.ACKNOWLEDGED: signals.incident_acknowledged,
    Status.RESOLVED: signals.incident_resolved,
}
MAX_NOTE_LENGTH = 5000


class IncidentError(Exception):
    """An incident change that breaks the rules, e.g. acknowledging a resolved incident."""


def _send_after_commit(status, incident, actor):
    transaction.on_commit(partial(SIGNALS[status].send, sender=Incident, incident=incident, actor=actor))


def _by(actor, via):
    if actor is not None:
        return f'by {actor.display_name}'
    return f'via {via}'


def add_timeline_entry(incident, kind, message, actor=None):
    return TimelineEntry.objects.create(incident=incident, kind=kind, message=message, actor=actor)


def find_open(service, dedup_key, lock=False):
    incidents = Incident.objects.filter(service=service, dedup_key=dedup_key, status__in=Incident.OPEN_STATUSES)
    if lock:
        incidents = incidents.select_for_update()
    return incidents.first()


def _record_repeat(incident, summary, actor, via):
    Incident.objects.filter(pk=incident.pk).update(alert_count=F('alert_count') + 1, updated_at=timezone.now())
    incident.refresh_from_db(fields=['alert_count', 'updated_at'])
    add_timeline_entry(incident, Kind.ALERT, f'Repeat alert {_by(actor, via)}: {summary}', actor)
    return incident


def trigger(service, summary, severity, dedup_key=None, details=None, source=Incident.Source.API, actor=None,
            via='the events API'):
    """Open an incident, or group the event into the open incident with the same dedup_key.

    Returns (incident, created). Two triggers racing with the same key can both find no open incident; the second
    insert then fails the partial unique constraint, and the event is recorded on the winner's incident instead.
    """
    summary = (summary or '').strip()
    if not summary:
        raise IncidentError('A summary is required.')
    if severity not in Severity.values:
        raise IncidentError(f"Severity must be one of: {', '.join(Severity.values)}.")
    dedup_key = dedup_key or uuid4().hex

    with transaction.atomic():
        existing = find_open(service, dedup_key, lock=True)
        if existing is not None:
            return _record_repeat(existing, summary, actor, via), False
        try:
            with transaction.atomic():
                incident = Incident.objects.create(
                    team_id=service.team_id, service=service, summary=summary[:255], severity=severity,
                    dedup_key=dedup_key, details=details or {}, source=source, created_by=actor,
                )
        except IntegrityError:
            existing = find_open(service, dedup_key, lock=True)
            if existing is None:
                raise
            return _record_repeat(existing, summary, actor, via), False
        add_timeline_entry(incident, Kind.TRIGGERED, f'Triggered {_by(actor, via)}: {incident.summary}', actor)
        _send_after_commit(Status.TRIGGERED, incident, actor)
    return incident, True


def can_transition(incident, status):
    return status in TRANSITIONS[incident.status]


def _transition(incident, status, actor, via):
    with transaction.atomic():
        locked = Incident.objects.select_for_update().get(pk=incident.pk)
        if not can_transition(locked, status):
            raise IncidentError(
                f"Incident #{locked.pk} is {locked.get_status_display().lower()}, so it can't be "
                f"{Status(status).label.lower()}."
            )
        now = timezone.now()
        locked.status = status
        if status == Status.ACKNOWLEDGED:
            locked.acknowledged_at, locked.acknowledged_by = now, actor
            fields = ['status', 'acknowledged_at', 'acknowledged_by', 'updated_at']
        else:
            locked.resolved_at, locked.resolved_by = now, actor
            fields = ['status', 'resolved_at', 'resolved_by', 'updated_at']
        locked.save(update_fields=fields)
        add_timeline_entry(locked, status, f'{Status(status).label} {_by(actor, via)}.', actor)
        _send_after_commit(status, locked, actor)
    for field in ('status', 'acknowledged_at', 'acknowledged_by', 'resolved_at', 'resolved_by', 'updated_at'):
        setattr(incident, field, getattr(locked, field))
    return incident


def acknowledge(incident, actor=None, via='the events API'):
    """Somebody is on it: stops escalation. Only triggered incidents can be acknowledged."""
    return _transition(incident, Status.ACKNOWLEDGED, actor, via)


def resolve(incident, actor=None, via='the events API'):
    """The problem is over. Triggered and acknowledged incidents can be resolved; resolved ones stay resolved."""
    return _transition(incident, Status.RESOLVED, actor, via)


def add_note(incident, actor, text):
    text = (text or '').strip()
    if not text:
        raise IncidentError('Write something first.')
    if len(text) > MAX_NOTE_LENGTH:
        raise IncidentError(f'Notes can be at most {MAX_NOTE_LENGTH} characters.')
    return add_timeline_entry(incident, Kind.NOTE, text, actor)


def incidents_for(user):
    """Incidents of every team the user belongs to, newest first."""
    return Incident.objects.filter(team__in=teams_for(user)).select_related('team', 'service')


def timeline_for(incident):
    return incident.timeline.select_related('actor')
