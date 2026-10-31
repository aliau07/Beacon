from django.conf import settings
from django.db import models


class Notification(models.Model):
    """An entry in someone's in-app inbox. Pages are also emailed."""

    class Kind(models.TextChoices):
        PAGE = 'page', 'Page'
        RESOLVED = 'resolved', 'Resolved'

    recipient  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    incident   = models.ForeignKey('incidents.Incident', null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    kind       = models.CharField(max_length=10, choices=Kind.choices)
    title      = models.CharField(max_length=255)
    body       = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['recipient', 'read_at'])]

    def __str__(self):
        return f'{self.recipient}: {self.title}'

    @property
    def is_read(self):
        return self.read_at is not None
