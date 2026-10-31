from functools import lru_cache
from zoneinfo import available_timezones

from django.core.exceptions import ValidationError


@lru_cache(maxsize=1)
def time_zone_names():
    """Every IANA time zone name known to zoneinfo, sorted (read once: scanning the tz database is slow)."""
    return sorted(available_timezones())


def time_zone_choices():
    return [(name, name.replace('_', ' ')) for name in time_zone_names()]


def validate_time_zone(value):
    if value not in time_zone_names():
        raise ValidationError('"%(value)s" is not an IANA time zone such as Europe/Dublin.', params={'value': value})
