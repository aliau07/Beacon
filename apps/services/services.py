"""Services and the API keys that send their events.

A key looks like bcn_1a2b3c4d_<43 random characters>. Beacon stores the prefix (bcn_1a2b3c4d) so people can tell
keys apart, and the SHA-256 hex digest of the whole key to check it; the key itself is returned once and never
stored.
"""
import hashlib
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.teams.services import Role, require_role

from .models import ApiKey, Service

KEY_PREFIX = 'bcn_'
MAX_KEY_LENGTH = 100
LAST_USED_PRECISION = timedelta(minutes=1)


class ServiceError(Exception):
    """A service change that breaks the rules, e.g. using another team's escalation policy."""


def hash_key(raw_key):
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_key():
    """(prefix, full key) for a new API key."""
    prefix = f'{KEY_PREFIX}{secrets.token_hex(4)}'
    return prefix, f'{prefix}_{secrets.token_urlsafe(32)}'


def _check(team, name, escalation_policy, service=None):
    if escalation_policy is not None and escalation_policy.team_id != team.pk:
        raise ServiceError('That escalation policy belongs to another team.')
    clash = Service.objects.filter(team=team, name__iexact=name.strip())
    if service is not None:
        clash = clash.exclude(pk=service.pk)
    if clash.exists():
        raise ServiceError('This team already has a service with that name.')


def create_service(team, actor, name, description='', escalation_policy=None):
    require_role(team, actor, Role.ADMIN, 'create services')
    _check(team, name, escalation_policy)
    return Service.objects.create(team=team, name=name.strip(), description=description, escalation_policy=escalation_policy)


def update_service(service, actor, name, description='', escalation_policy=None):
    require_role(service.team, actor, Role.ADMIN, 'change services')
    _check(service.team, name, escalation_policy, service)
    service.name, service.description, service.escalation_policy = name.strip(), description, escalation_policy
    service.save(update_fields=['name', 'description', 'escalation_policy', 'updated_at'])
    return service


def create_api_key(service, actor, name):
    """Returns (ApiKey, full key). Show the full key to the user now: it can't be recovered later."""
    require_role(service.team, actor, Role.ADMIN, 'create API keys')
    for _ in range(5):
        prefix, raw_key = generate_key()
        try:
            with transaction.atomic():
                api_key = ApiKey.objects.create(
                    service=service, name=name.strip(), prefix=prefix, key_hash=hash_key(raw_key), created_by=actor,
                )
        except IntegrityError:
            continue  # prefix collision: 1 in 4 billion, just draw again
        return api_key, raw_key
    raise ServiceError('Could not generate a unique API key; please try again.')


def revoke_api_key(api_key, actor):
    require_role(api_key.service.team, actor, Role.ADMIN, 'revoke API keys')
    if api_key.revoked_at is None:
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=['revoked_at'])
    return api_key


def authenticate(raw_key):
    """The active ApiKey matching `raw_key`, or None. Records when the key was last used (to the minute)."""
    if not raw_key or not raw_key.startswith(KEY_PREFIX) or len(raw_key) > MAX_KEY_LENGTH:
        return None
    api_key = (ApiKey.objects.select_related('service__team')
               .filter(key_hash=hash_key(raw_key), revoked_at__isnull=True).first())
    if api_key is None or not secrets.compare_digest(raw_key[:len(api_key.prefix)], api_key.prefix):
        return None
    now = timezone.now()
    if api_key.last_used_at is None or now - api_key.last_used_at >= LAST_USED_PRECISION:
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
        api_key.last_used_at = now
    return api_key
