from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse

from apps.core.validators import validate_time_zone


class Schedule(models.Model):
    """Who is on call for a team: one or more rotations, plus overrides that win over them."""

    team        = models.ForeignKey('teams.Team', on_delete=models.CASCADE, related_name='schedules')
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['team', 'name'], name='oncall_unique_schedule_name')]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('oncall:schedule_detail', args=[self.pk])


class Rotation(models.Model):
    """A layer of a schedule. Participants take turns; each shift lasts `shift_length_days` and hands off at
    `handoff_time` on the local clock of `time_zone`, so a 09:00 handoff stays at 09:00 across DST changes."""

    schedule          = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='rotations')
    name              = models.CharField(max_length=100)
    time_zone         = models.CharField(max_length=64, validators=[validate_time_zone])
    start_date        = models.DateField(help_text='Local date of the first handoff.')
    handoff_time      = models.TimeField(default=time(9, 0), help_text='Local clock time of every handoff.')
    shift_length_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(365)], help_text='1 for daily, 7 for weekly.',
    )
    priority          = models.PositiveSmallIntegerField(
        default=1, help_text='When rotations overlap, the highest priority layer decides who is on call.',
    )
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-priority', 'pk']

    def __str__(self):
        return f'{self.schedule}: {self.name}'


class RotationParticipant(models.Model):
    rotation = models.ForeignKey(Rotation, on_delete=models.CASCADE, related_name='participants')
    user     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['rotation', 'position'], name='oncall_unique_rotation_position')]

    def __str__(self):
        return f'{self.position + 1}. {self.user}'


class Override(models.Model):
    """`user` is on call for the schedule from `starts_at` until (not including) `ends_at`, whatever the rotations say."""

    schedule   = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='overrides')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    starts_at  = models.DateTimeField()
    ends_at    = models.DateTimeField()
    reason     = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at']
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='oncall_override_ends_after_start')]
        indexes = [models.Index(fields=['schedule', 'starts_at', 'ends_at'])]

    def __str__(self):
        return f'{self.user} on {self.schedule} from {self.starts_at:%Y-%m-%d %H:%M}'
