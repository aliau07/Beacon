from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Demo data for local development. It sits on top of every other app; nothing depends on it."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'apps.demo'
