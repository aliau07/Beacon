from django.apps import AppConfig


class EscalationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.escalation'

    def ready(self):
        from . import receivers  # noqa: F401
