from django.db import models
from django.urls import reverse


class ComponentStatus(models.TextChoices):
    OPERATIONAL = 'operational', 'Operational'
    MAINTENANCE = 'maintenance', 'Under maintenance'
    MINOR = 'minor', 'Minor issue'
    DEGRADED = 'degraded', 'Degraded performance'
    PARTIAL_OUTAGE = 'partial_outage', 'Partial outage'
    MAJOR_OUTAGE = 'major_outage', 'Major outage'


class StatusPage(models.Model):
    """A team's public page at /status/<slug>/, showing how each component is doing."""

    team        = models.OneToOneField('teams.Team', on_delete=models.CASCADE, related_name='status_page')
    title       = models.CharField(max_length=100)
    slug        = models.SlugField(max_length=60, unique=True, help_text='The public address: /status/<slug>/.')
    description = models.TextField(blank=True)
    is_public   = models.BooleanField(default=True, help_text='Untick to hide the page from the public.')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('statuspage:public', args=[self.slug])


class Component(models.Model):
    """Something customers recognise ("Checkout", "API"). Its status is the worst open incident severity of its
    linked services, unless a team admin sets an override."""

    status_page      = models.ForeignKey(StatusPage, on_delete=models.CASCADE, related_name='components')
    name             = models.CharField(max_length=100)
    description      = models.CharField(max_length=255, blank=True)
    position         = models.PositiveSmallIntegerField(default=0)
    services         = models.ManyToManyField('services.Service', blank=True, related_name='status_components')
    override_status  = models.CharField(
        max_length=20, choices=ComponentStatus.choices, blank=True,
        help_text='Leave empty to follow the linked services automatically.',
    )
    override_message = models.CharField(max_length=255, blank=True, help_text='Shown publicly next to the component.')

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name
