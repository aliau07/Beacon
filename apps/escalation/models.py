from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse


class EscalationPolicy(models.Model):
    """Who to page, in order, until somebody acknowledges an incident."""

    team         = models.ForeignKey('teams.Team', on_delete=models.CASCADE, related_name='escalation_policies')
    name         = models.CharField(max_length=100)
    description  = models.TextField(blank=True)
    repeat_count = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(9)],
        help_text='If nobody acknowledges after the last level, start again from level 1 this many more times.',
    )
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'escalation policies'
        constraints = [models.UniqueConstraint(fields=['team', 'name'], name='escalation_unique_policy_name')]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('escalation:policy_detail', args=[self.pk])


class EscalationLevel(models.Model):
    """One step of a policy: page a user, or whoever is on call for a schedule, then wait `delay_minutes`."""

    policy          = models.ForeignKey(EscalationPolicy, on_delete=models.CASCADE, related_name='levels')
    position        = models.PositiveSmallIntegerField()
    delay_minutes   = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(1), MaxValueValidator(24 * 60)],
        help_text='Minutes to wait for an acknowledgement before paging the next level.',
    )
    target_user     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.RESTRICT, related_name='+')
    target_schedule = models.ForeignKey('oncall.Schedule', null=True, blank=True, on_delete=models.RESTRICT, related_name='escalation_levels')

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['policy', 'position'], name='escalation_unique_level_position'),
            models.CheckConstraint(
                condition=Q(target_user__isnull=False, target_schedule__isnull=True)
                | Q(target_user__isnull=True, target_schedule__isnull=False),
                name='escalation_level_has_one_target',
            ),
        ]

    def __str__(self):
        return f'Level {self.number}: {self.target_label}'

    @property
    def number(self):
        return self.position + 1

    @property
    def target_label(self):
        if self.target_schedule_id:
            return f'on call for {self.target_schedule.name}'
        return self.target_user.display_name


class EscalationState(models.Model):
    """How far an incident has got through its policy. `next_run_at` is when the next level is due; it is cleared
    once the incident is acknowledged or resolved, or the policy runs out of levels and repeats."""

    incident    = models.OneToOneField('incidents.Incident', on_delete=models.CASCADE, related_name='escalation')
    policy      = models.ForeignKey(EscalationPolicy, on_delete=models.CASCADE, related_name='+')
    level_index = models.PositiveSmallIntegerField(default=0, help_text='Index of the level paged most recently.')
    cycle       = models.PositiveSmallIntegerField(default=0, help_text='How many repeats have started.')
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Escalation of incident {self.incident_id}'
