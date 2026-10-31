from django.dispatch import receiver

from apps.incidents.signals import incident_acknowledged, incident_resolved, incident_triggered

from . import services


@receiver(incident_triggered)
def start_escalation(sender, incident, **kwargs):
    services.start(incident)


@receiver(incident_acknowledged)
@receiver(incident_resolved)
def stop_escalation(sender, incident, **kwargs):
    services.stop(incident)
