from django.apps import AppConfig


class PostmortemsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.postmortems'

    def ready(self):
        from . import receivers  # noqa: F401
