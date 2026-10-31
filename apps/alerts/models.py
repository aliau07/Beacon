from django.db import models


class Alert(models.Model):
    """One event accepted by the events API, kept as the record of what monitoring sent and what Beacon did."""

    class Action(models.TextChoices):
        TRIGGER = 'trigger', 'Trigger'
        ACKNOWLEDGE = 'acknowledge', 'Acknowledge'
        RESOLVE = 'resolve', 'Resolve'

    class Outcome(models.TextChoices):
        TRIGGERED = 'triggered', 'Opened an incident'
        DEDUPLICATED = 'deduplicated', 'Grouped into the open incident'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged the incident'
        RESOLVED = 'resolved', 'Resolved the incident'
        IGNORED = 'ignored', 'Ignored'

    service     = models.ForeignKey('services.Service', on_delete=models.CASCADE, related_name='alerts')
    incident    = models.ForeignKey('incidents.Incident', null=True, blank=True, on_delete=models.SET_NULL, related_name='alerts')
    api_key     = models.ForeignKey('services.ApiKey', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action      = models.CharField(max_length=12, choices=Action.choices)
    outcome     = models.CharField(max_length=12, choices=Outcome.choices)
    dedup_key   = models.CharField(max_length=255)
    summary     = models.CharField(max_length=255, blank=True)
    severity    = models.CharField(max_length=10, blank=True)
    payload     = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at', '-pk']

    def __str__(self):
        return f'{self.action} {self.dedup_key} ({self.outcome})'


class RateLimitWindow(models.Model):
    """How many requests one API key has made in one fixed window (EVENTS_RATE_LIMIT_WINDOW seconds)."""

    api_key      = models.ForeignKey('services.ApiKey', on_delete=models.CASCADE, related_name='+')
    window_start = models.DateTimeField()
    count        = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['api_key', 'window_start'], name='alerts_one_window_per_key')]

    def __str__(self):
        return f'{self.api_key_id} @ {self.window_start:%H:%M:%S}: {self.count}'
