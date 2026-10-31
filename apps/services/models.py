from django.conf import settings
from django.db import models
from django.urls import reverse


class Service(models.Model):
    """Something that can break (an API, a worker, a database). Its incidents follow its escalation policy."""

    team              = models.ForeignKey('teams.Team', on_delete=models.CASCADE, related_name='services')
    name              = models.CharField(max_length=100)
    description       = models.TextField(blank=True)
    escalation_policy = models.ForeignKey(
        'escalation.EscalationPolicy', null=True, blank=True, on_delete=models.SET_NULL, related_name='services',
    )
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['team', 'name'], name='services_unique_service_name')]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('services:detail', args=[self.pk])


class ApiKey(models.Model):
    """A secret that lets a monitoring tool send events for one service.

    The full key is shown once when it is created. Only its prefix (to recognise it) and the SHA-256 hash of the
    whole key (to check it) are stored.
    """

    service      = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='api_keys')
    name         = models.CharField(max_length=100, help_text='Where the key is used, e.g. "Prometheus Alertmanager".')
    prefix       = models.CharField(max_length=16, unique=True)
    key_hash     = models.CharField(max_length=64, unique=True)
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'API key'

    def __str__(self):
        return f'{self.prefix}… ({self.name})'

    @property
    def is_active(self):
        return self.revoked_at is None
