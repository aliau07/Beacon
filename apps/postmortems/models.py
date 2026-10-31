from django.conf import settings
from django.db import models
from django.urls import reverse


class Postmortem(models.Model):
    """What happened in a resolved incident, why, and what the team will change. Starts with the incident's timeline
    copied in, so the write-up begins from the facts."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'

    incident     = models.OneToOneField('incidents.Incident', on_delete=models.CASCADE, related_name='postmortem')
    title        = models.CharField(max_length=200)
    impact       = models.TextField(blank=True, help_text='Who was affected, how badly and for how long.')
    root_cause   = models.TextField(blank=True, help_text='Why it happened, not who did it.')
    status       = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('postmortems:detail', args=[self.pk])


class PostmortemEvent(models.Model):
    postmortem  = models.ForeignKey(Postmortem, on_delete=models.CASCADE, related_name='events')
    occurred_at = models.DateTimeField()
    description = models.TextField()

    class Meta:
        ordering = ['occurred_at', 'pk']

    def __str__(self):
        return f'{self.occurred_at:%H:%M} {self.description[:50]}'


class ActionItem(models.Model):
    postmortem   = models.ForeignKey(Postmortem, on_delete=models.CASCADE, related_name='action_items')
    description  = models.CharField(max_length=255)
    owner        = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    due_date     = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['completed_at', 'due_date', 'pk']

    def __str__(self):
        return self.description

    @property
    def is_done(self):
        return self.completed_at is not None


class Screenshot(models.Model):
    """A graph or dashboard capture. Stored resized and re-encoded, so photo metadata (EXIF) is gone."""

    postmortem  = models.ForeignKey(Postmortem, on_delete=models.CASCADE, related_name='screenshots')
    image       = models.ImageField(upload_to='postmortems/%Y/%m/')
    caption     = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return self.caption or self.image.name
