"""Telling people about incidents: a page lands in the in-app inbox and is emailed (after the transaction commits,
so nobody is emailed about a change that was rolled back)."""
from functools import partial

from django.db import transaction
from django.utils import timezone

from apps.core.notifications import notify

from .models import Notification

Kind = Notification.Kind


def _deliver(user, incident, kind, title, body, template_name):
    notification = Notification.objects.create(recipient=user, incident=incident, kind=kind, title=title, body=body)
    transaction.on_commit(partial(notify, user, title, template_name, {
        'incident': incident, 'reason': body, 'incident_path': incident.get_absolute_url(),
    }))
    return notification


def page(user, incident, reason):
    """Page `user` about `incident`; `reason` says why them (e.g. "Default policy, level 2 via Primary")."""
    title = f'[{incident.get_severity_display()}] #{incident.pk} {incident.summary}'
    return _deliver(user, incident, Kind.PAGE, title[:255], reason, 'notifications/emails/page.txt')


def notify_resolved(incident, actor=None):
    """Tell everyone who was paged for `incident` that it is over (except whoever resolved it)."""
    paged_users = {}
    for notification in Notification.objects.filter(incident=incident, kind=Kind.PAGE).select_related('recipient'):
        paged_users[notification.recipient_id] = notification.recipient
    resolver = f'by {actor.display_name}' if actor else 'automatically'
    for user_id, user in paged_users.items():
        if actor is not None and user_id == actor.pk:
            continue
        _deliver(user, incident, Kind.RESOLVED, f'Resolved: #{incident.pk} {incident.summary}'[:255],
                 f'Resolved {resolver}.', 'notifications/emails/resolved.txt')


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def inbox_for(user):
    return Notification.objects.filter(recipient=user).select_related('incident')


def mark_read(notification):
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    return notification


def mark_all_read(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(read_at=timezone.now())
