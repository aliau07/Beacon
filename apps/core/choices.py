from django.db import models


class Severity(models.TextChoices):
    """How bad an incident is. Shared by alerts, incidents and status pages; listed worst first."""

    CRITICAL = 'critical', 'Critical'
    ERROR = 'error', 'Error'
    WARNING = 'warning', 'Warning'
    INFO = 'info', 'Info'


SEVERITY_RANK = {Severity.CRITICAL: 4, Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}

SEVERITY_BADGE = {
    Severity.CRITICAL: 'text-bg-danger',
    Severity.ERROR: 'text-bg-warning',
    Severity.WARNING: 'text-bg-info',
    Severity.INFO: 'text-bg-secondary',
}


def worst_severity(severities):
    """The worst of `severities` (e.g. ['info', 'critical'] -> 'critical'), or None when there are none."""
    worst = None
    for severity in severities:
        if worst is None or SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(worst, 0):
            worst = severity
    return worst
