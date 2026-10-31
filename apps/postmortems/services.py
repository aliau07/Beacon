"""Postmortems for resolved incidents: timeline copied from the incident, impact pre-filled from its facts, then
root cause, action items and screenshots added by the team."""
from django.conf import settings
from django.db import transaction
from django.template.defaultfilters import date as date_format
from django.utils import timezone

from apps.core.images import ImageError, process_image
from apps.core.templatetags.core_extras import duration
from apps.incidents.services import timeline_for
from apps.teams.services import Role, is_member, require_role

from .models import ActionItem, Postmortem, PostmortemEvent, Screenshot

MAX_SCREENSHOT_SIZE = (1600, 1600)
MAX_SCREENSHOTS = 20


class PostmortemError(Exception):
    """A postmortem change that breaks the rules, e.g. one for an incident that is still open."""


def _require_member(postmortem, actor):
    require_role(postmortem.incident.team, actor, Role.RESPONDER, 'edit postmortems')


def draft_impact(incident):
    lines = [
        f'Service: {incident.service.name}',
        f'Severity: {incident.get_severity_display()}',
        f'Open for {duration(incident.duration)}: {date_format(incident.created_at, "j M Y H:i")} to '
        f'{date_format(incident.resolved_at, "j M Y H:i")} ({timezone.get_current_timezone_name()}).',
        f'Alerts grouped into the incident: {incident.alert_count}.',
    ]
    if incident.acknowledged_at:
        lines.append(f'Acknowledged after {duration(incident.acknowledged_at - incident.created_at)}.')
    return '\n'.join(lines)


def start_postmortem(incident, actor):
    """Create the incident's postmortem with its timeline and the known facts filled in."""
    require_role(incident.team, actor, Role.RESPONDER, 'write postmortems')
    if incident.is_open:
        raise PostmortemError('Resolve the incident before writing its postmortem.')
    if Postmortem.objects.filter(incident=incident).exists():
        raise PostmortemError('This incident already has a postmortem.')
    with transaction.atomic():
        postmortem = Postmortem.objects.create(
            incident=incident, title=f'Postmortem: {incident.summary}'[:200], impact=draft_impact(incident),
            created_by=actor,
        )
        for entry in timeline_for(incident):
            PostmortemEvent.objects.create(postmortem=postmortem, occurred_at=entry.created_at, description=entry.message)
    return postmortem


def update_postmortem(postmortem, actor, title, impact, root_cause):
    _require_member(postmortem, actor)
    postmortem.title, postmortem.impact, postmortem.root_cause = title, impact, root_cause
    postmortem.save(update_fields=['title', 'impact', 'root_cause', 'updated_at'])
    return postmortem


def publish(postmortem, actor):
    _require_member(postmortem, actor)
    if not postmortem.root_cause.strip():
        raise PostmortemError('Write down the root cause before publishing.')
    postmortem.status, postmortem.published_at = Postmortem.Status.PUBLISHED, timezone.now()
    postmortem.save(update_fields=['status', 'published_at', 'updated_at'])
    return postmortem


def add_event(postmortem, actor, occurred_at, description):
    _require_member(postmortem, actor)
    return PostmortemEvent.objects.create(postmortem=postmortem, occurred_at=occurred_at, description=description)


def add_action_item(postmortem, actor, description, owner=None, due_date=None):
    _require_member(postmortem, actor)
    if owner is not None and not is_member(postmortem.incident.team, owner):
        raise PostmortemError(f'{owner.username} is not on {postmortem.incident.team.name}.')
    return ActionItem.objects.create(postmortem=postmortem, description=description, owner=owner, due_date=due_date)


def toggle_action_item(item, actor):
    _require_member(item.postmortem, actor)
    item.completed_at = None if item.completed_at else timezone.now()
    item.save(update_fields=['completed_at'])
    return item


def add_screenshot(postmortem, actor, upload, caption=''):
    """Store the upload resized to fit 1600x1600 and re-encoded (EXIF stripped)."""
    _require_member(postmortem, actor)
    if postmortem.screenshots.count() >= MAX_SCREENSHOTS:
        raise PostmortemError(f'A postmortem can have at most {MAX_SCREENSHOTS} screenshots.')
    if upload.size > settings.MAX_SCREENSHOT_SIZE_MB * 1024 * 1024:
        raise PostmortemError(f'Screenshots can be at most {settings.MAX_SCREENSHOT_SIZE_MB} MB.')
    try:
        content = process_image(upload, MAX_SCREENSHOT_SIZE)
    except ImageError as error:
        raise PostmortemError(str(error)) from error
    screenshot = Screenshot(postmortem=postmortem, caption=caption, uploaded_by=actor)
    screenshot.image.save(content.name, content, save=False)
    screenshot.save()
    return screenshot


def delete_screenshot(screenshot, actor):
    _require_member(screenshot.postmortem, actor)
    screenshot.delete()
