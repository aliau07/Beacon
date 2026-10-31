"""Small builders shared by the test suites of every app (test code may import across apps)."""
import itertools
import shutil
import tempfile
from datetime import date, time
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from apps.escalation.models import EscalationLevel, EscalationPolicy
from apps.incidents.models import Incident
from apps.oncall.models import Override, Rotation, RotationParticipant, Schedule
from apps.services.models import ApiKey, Service
from apps.services.services import generate_key, hash_key
from apps.teams.models import Membership, Team

Role = Membership.Role
_counter = itertools.count(1)


def make_user(username=None, **extra):
    username = username or f'user{next(_counter)}'
    extra.setdefault('email', f'{username}@example.com')
    return get_user_model().objects.create_user(username, **extra)


def make_team(name=None, owner=None):
    """A team with an owner (a new user unless `owner` is given)."""
    number = next(_counter)
    team = Team.objects.create(name=name or f'Team {number}', slug=f'team-{number}')
    Membership.objects.create(team=team, user=owner or make_user(), role=Role.OWNER)
    return team


def owner_of(team):
    return team.memberships.filter(role=Role.OWNER).first().user


def add_member(team, user=None, role=Role.RESPONDER):
    user = user or make_user()
    Membership.objects.create(team=team, user=user, role=role)
    return user


def make_service(team=None, name=None, policy=None):
    team = team or make_team()
    return Service.objects.create(team=team, name=name or f'Service {next(_counter)}', escalation_policy=policy)


def make_api_key(service=None, name='Monitoring'):
    """(ApiKey, full key) created directly, without the permission check."""
    service = service or make_service()
    prefix, raw_key = generate_key()
    api_key = ApiKey.objects.create(service=service, name=name, prefix=prefix, key_hash=hash_key(raw_key))
    return api_key, raw_key


def make_incident(service=None, status=Incident.Status.TRIGGERED, severity='error', summary='Disk full on db1',
                  dedup_key=None, **extra):
    """An incident saved directly, without timeline entries or signals."""
    service = service or make_service()
    return Incident.objects.create(team_id=service.team_id, service=service, status=status, severity=severity,
                                   summary=summary, dedup_key=dedup_key or f'key-{next(_counter)}', **extra)


def make_schedule(team=None, name=None):
    return Schedule.objects.create(team=team or make_team(), name=name or f'Schedule {next(_counter)}')


def make_rotation(schedule, users, time_zone='UTC', start_date=date(2026, 1, 5), handoff_time=time(9, 0),
                  shift_length_days=7, priority=1, name='Primary'):
    rotation = Rotation.objects.create(schedule=schedule, name=name, time_zone=time_zone, start_date=start_date,
                                       handoff_time=handoff_time, shift_length_days=shift_length_days, priority=priority)
    for position, user in enumerate(users):
        RotationParticipant.objects.create(rotation=rotation, user=user, position=position)
    return rotation


def make_override(schedule, user, starts_at, ends_at, **extra):
    return Override.objects.create(schedule=schedule, user=user, starts_at=starts_at, ends_at=ends_at, **extra)


def make_policy(team, targets, delay_minutes=5, repeat_count=0, name=None):
    """A policy with one level per target (a user or a Schedule), each waiting `delay_minutes`."""
    policy = EscalationPolicy.objects.create(team=team, name=name or f'Policy {next(_counter)}', repeat_count=repeat_count)
    for position, target in enumerate(targets):
        level = EscalationLevel(policy=policy, position=position, delay_minutes=delay_minutes)
        if isinstance(target, Schedule):
            level.target_schedule = target
        else:
            level.target_user = target
        level.save()
    return policy


def image_upload(name='shot.jpg', size=(64, 48), image_format='JPEG', colour=(200, 30, 30), exif=None, mode='RGB'):
    buffer = BytesIO()
    image = Image.new(mode, size, colour)
    if exif is not None:
        image.save(buffer, format=image_format, exif=exif)
    else:
        image.save(buffer, format=image_format)
    content_type = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'GIF': 'image/gif', 'WEBP': 'image/webp',
                    'BMP': 'image/bmp'}[image_format]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class TemporaryMediaMixin:
    """Store uploads in a throwaway directory for the duration of a test class."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='beacon-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        cls.addClassCleanup(shutil.rmtree, cls._media_root, ignore_errors=True)
        cls.addClassCleanup(cls._media_override.disable)
        super().setUpClass()
