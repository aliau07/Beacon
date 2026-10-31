from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.validators import validate_time_zone


class User(AbstractUser):
    """A Beacon user. Times are shown in their own time zone and pages go to their email address."""

    time_zone = models.CharField(
        max_length=64, default='UTC', validators=[validate_time_zone],
        help_text='IANA name such as Europe/Dublin; times across Beacon are shown in it.',
    )
    avatar = models.ImageField(upload_to='avatars/', blank=True)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        if self.first_name and self.last_name:
            return f'{self.first_name[0]}{self.last_name[0]}'.upper()
        return self.username[:2].upper()
