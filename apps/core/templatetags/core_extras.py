from django import template

from ..choices import SEVERITY_BADGE

register = template.Library()


@register.filter
def severity_badge(severity):
    """Bootstrap badge classes for a severity: critical -> text-bg-danger."""
    return SEVERITY_BADGE.get(severity, 'text-bg-secondary')


@register.filter
def duration(delta):
    """A timedelta as a short duration: 1 day, 2:05:00 -> 1d 2h 5m; under a minute -> <1m."""
    if delta in (None, ''):
        return ''
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return '<1m'
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    if minutes:
        parts.append(f'{minutes}m')
    return ' '.join(parts)
