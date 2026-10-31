from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.choices import Severity


class Incident(models.Model):
    """A problem on a service: triggered -> acknowledged -> resolved, or straight from triggered to resolved.

    Events with the same dedup_key are grouped into the service's one open incident for that key; the partial
    unique constraint makes that hold even when two events arrive at the same moment.
    """

    class Status(models.TextChoices):
        TRIGGERED = 'triggered', 'Triggered'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        RESOLVED = 'resolved', 'Resolved'

    class Source(models.TextChoices):
        API = 'api', 'Events API'
        WEB = 'web', 'Created in Beacon'

    OPEN_STATUSES = ['triggered', 'acknowledged']
    STATUS_BADGES = {'triggered': 'text-bg-danger', 'acknowledged': 'text-bg-warning', 'resolved': 'text-bg-success'}

    team            = models.ForeignKey('teams.Team', on_delete=models.CASCADE, related_name='incidents')
    service         = models.ForeignKey('services.Service', on_delete=models.CASCADE, related_name='incidents')
    summary         = models.CharField(max_length=255)
    severity        = models.CharField(max_length=10, choices=Severity.choices)
    status          = models.CharField(max_length=12, choices=Status.choices, default=Status.TRIGGERED)
    dedup_key       = models.CharField(max_length=255)
    details         = models.JSONField(default=dict, blank=True)
    source          = models.CharField(max_length=3, choices=Source.choices, default=Source.API)
    alert_count     = models.PositiveIntegerField(default=1, help_text='Events grouped into this incident.')
    created_by      = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    resolved_at     = models.DateTimeField(null=True, blank=True)
    resolved_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['service', 'dedup_key'], condition=Q(status__in=['triggered', 'acknowledged']),
                name='incidents_one_open_incident_per_dedup_key',
            ),
        ]
        indexes = [models.Index(fields=['team', 'status'])]

    def __str__(self):
        return f'#{self.pk} {self.summary}'

    def get_absolute_url(self):
        return reverse('incidents:detail', args=[self.pk])

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def status_badge(self):
        return self.STATUS_BADGES[self.status]

    @property
    def duration(self):
        """How long the incident was (or has been) open."""
        return (self.resolved_at or timezone.now()) - self.created_at


class TimelineEntry(models.Model):
    """Something that happened to an incident. Every state change, page, escalation and note is recorded."""

    class Kind(models.TextChoices):
        TRIGGERED = 'triggered', 'Triggered'
        ALERT = 'alert', 'Repeat alert'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        RESOLVED = 'resolved', 'Resolved'
        ESCALATED = 'escalated', 'Escalated'
        PAGED = 'paged', 'Paged'
        NOTE = 'note', 'Note'

    incident   = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='timeline')
    kind       = models.CharField(max_length=12, choices=Kind.choices)
    message    = models.TextField()
    actor      = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        verbose_name_plural = 'timeline entries'

    def __str__(self):
        return f'{self.get_kind_display()}: {self.message[:60]}'
