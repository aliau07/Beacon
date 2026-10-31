from django.conf import settings
from django.db import models
from django.urls import reverse


class Team(models.Model):
    """The group that owns services, schedules, escalation policies and a status page."""

    name       = models.CharField(max_length=100, unique=True)
    slug       = models.SlugField(max_length=110, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('teams:detail', args=[self.slug])


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        RESPONDER = 'responder', 'Responder'

    team       = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    role       = models.CharField(max_length=10, choices=Role.choices, default=Role.RESPONDER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['team', 'user__username']
        constraints = [models.UniqueConstraint(fields=['team', 'user'], name='teams_one_membership_per_user')]

    def __str__(self):
        return f'{self.user} ({self.get_role_display()}) in {self.team}'
