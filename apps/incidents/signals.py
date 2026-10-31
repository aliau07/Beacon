"""Events other apps react to (escalation, notifications) without the incidents app knowing about them.

Each signal is sent after the transaction commits, with sender=Incident, the incident as `incident` and the user
who caused it (or None for the events API) as `actor`.
"""
from django.dispatch import Signal

incident_triggered = Signal()

incident_acknowledged = Signal()

incident_resolved = Signal()
