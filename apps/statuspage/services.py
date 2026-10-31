"""Status pages. A component's status comes from the worst open incident on its linked services:

    critical -> major outage, error -> partial outage, warning -> degraded performance, info -> minor issue

and is operational when none of them has an open incident. A manual override always wins.
"""
from django.db import transaction
from django.utils import timezone

from apps.core.choices import Severity, worst_severity
from apps.incidents.models import Incident
from apps.teams.services import Role, require_role

from .models import Component, ComponentStatus, StatusPage

STATUS_FOR_SEVERITY = {
    Severity.CRITICAL: ComponentStatus.MAJOR_OUTAGE,
    Severity.ERROR: ComponentStatus.PARTIAL_OUTAGE,
    Severity.WARNING: ComponentStatus.DEGRADED,
    Severity.INFO: ComponentStatus.MINOR,
}
STATUS_RANK = {
    ComponentStatus.OPERATIONAL: 0, ComponentStatus.MAINTENANCE: 1, ComponentStatus.MINOR: 2,
    ComponentStatus.DEGRADED: 3, ComponentStatus.PARTIAL_OUTAGE: 4, ComponentStatus.MAJOR_OUTAGE: 5,
}
STATUS_CSS = {
    ComponentStatus.OPERATIONAL: 'success', ComponentStatus.MAINTENANCE: 'info', ComponentStatus.MINOR: 'secondary',
    ComponentStatus.DEGRADED: 'warning', ComponentStatus.PARTIAL_OUTAGE: 'orange', ComponentStatus.MAJOR_OUTAGE: 'danger',
}
OVERALL_LABELS = {
    ComponentStatus.OPERATIONAL: 'All systems operational',
    ComponentStatus.MAINTENANCE: 'Scheduled maintenance in progress',
    ComponentStatus.MINOR: 'Minor issues',
    ComponentStatus.DEGRADED: 'Some systems are degraded',
    ComponentStatus.PARTIAL_OUTAGE: 'Partial outage',
    ComponentStatus.MAJOR_OUTAGE: 'Major outage',
}
REFRESH_SECONDS = 30


class StatusPageError(Exception):
    """A status page change that breaks the rules, e.g. linking another team's service."""


def status_for_severity(severity):
    return STATUS_FOR_SEVERITY.get(severity, ComponentStatus.OPERATIONAL)


def worst_status(statuses):
    worst = ComponentStatus.OPERATIONAL
    for status in statuses:
        if STATUS_RANK[status] > STATUS_RANK[worst]:
            worst = status
    return worst


def _open_severities_by_service(service_ids):
    severities = {}
    open_incidents = Incident.objects.filter(service_id__in=service_ids, status__in=Incident.OPEN_STATUSES)
    for service_id, severity in open_incidents.values_list('service_id', 'severity'):
        severities.setdefault(service_id, []).append(severity)
    return severities


def automatic_status(component, severities_by_service=None):
    """The status implied by the worst open incident on the component's services."""
    service_ids = list(component.services.values_list('pk', flat=True))
    if severities_by_service is None:
        severities_by_service = _open_severities_by_service(service_ids)
    severities = []
    for service_id in service_ids:
        severities.extend(severities_by_service.get(service_id, []))
    return status_for_severity(worst_severity(severities))


def component_status(component, severities_by_service=None):
    return component.override_status or automatic_status(component, severities_by_service)


def summary(status_page):
    """Everything the public page shows, as plain data (also served as JSON for the 30-second refresh)."""
    components = list(status_page.components.prefetch_related('services'))
    service_ids = set()
    for component in components:
        for service in component.services.all():
            service_ids.add(service.pk)
    severities = _open_severities_by_service(service_ids)

    rows = []
    for component in components:
        status = component_status(component, severities)
        rows.append({
            'id': component.pk,
            'name': component.name,
            'description': component.description,
            'status': status,
            'status_label': ComponentStatus(status).label,
            'css': STATUS_CSS[status],
            'message': component.override_message,
            'overridden': bool(component.override_status),
        })
    overall = worst_status([row['status'] for row in rows])
    return {
        'title': status_page.title,
        'status': overall,
        'status_label': OVERALL_LABELS[overall],
        'css': STATUS_CSS[overall],
        'components': rows,
        'updated_at': timezone.now().isoformat(),
        'refresh_seconds': REFRESH_SECONDS,
    }


def public_page(slug):
    return StatusPage.objects.filter(slug=slug, is_public=True).first()


def save_page(team, actor, title, slug, description='', is_public=True):
    require_role(team, actor, Role.ADMIN, 'change the status page')
    if StatusPage.objects.filter(slug=slug).exclude(team=team).exists():
        raise StatusPageError('That address is taken by another status page.')
    page, _ = StatusPage.objects.update_or_create(team=team, defaults={
        'title': title, 'slug': slug, 'description': description, 'is_public': is_public,
    })
    return page


def _check_services(status_page, services):
    for service in services:
        if service.team_id != status_page.team_id:
            raise StatusPageError(f'{service.name} belongs to another team.')


def save_component(status_page, actor, name, services, description='', position=0, override_status='',
                   override_message='', component=None):
    """Create or update a component; `services` are the team services whose incidents drive its status."""
    require_role(status_page.team, actor, Role.ADMIN, 'change the status page')
    _check_services(status_page, services)
    if override_status and override_status not in ComponentStatus.values:
        raise StatusPageError('Unknown status.')
    with transaction.atomic():
        component = component or Component(status_page=status_page)
        component.name, component.description, component.position = name, description, position
        component.override_status, component.override_message = override_status, override_message
        component.save()
        component.services.set(services)
    return component


def set_override(component, actor, status, message=''):
    """Pin the component's public status (e.g. maintenance); pass status='' to go back to automatic."""
    require_role(component.status_page.team, actor, Role.ADMIN, 'change the status page')
    if status and status not in ComponentStatus.values:
        raise StatusPageError('Unknown status.')
    component.override_status, component.override_message = status, message if status else ''
    component.save(update_fields=['override_status', 'override_message'])
    return component


def delete_component(component, actor):
    require_role(component.status_page.team, actor, Role.ADMIN, 'change the status page')
    component.delete()
