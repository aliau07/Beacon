from django.dispatch import receiver

from apps.incidents.signals import incident_resolved

from .services import notify_resolved


@receiver(incident_resolved)
def tell_paged_people(sender, incident, actor=None, **kwargs):
    notify_resolved(incident, actor)
