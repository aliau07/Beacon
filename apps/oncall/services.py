"""On-call schedules: who is on call at any moment, from rotations (local-clock handoffs that survive DST changes)
and overrides (which always win).

All arithmetic on instants is done in UTC. Python compares and subtracts datetimes that share a tzinfo by wall
clock, which goes wrong in the hour that repeats when clocks fall back.
"""
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.teams.services import Role, has_role, is_member, require_role

from .models import Override, Rotation, RotationParticipant, Schedule

Shift = namedtuple('Shift', 'index first_day starts_at ends_at')
Segment = namedtuple('Segment', 'starts_at ends_at user source')

MAX_OVERRIDE_DAYS = 31
MAX_HANDOFFS = 2000


class OnCallError(Exception):
    """A schedule change that breaks the rules, e.g. a rotation with someone who isn't on the team."""


# Rotation arithmetic ---------------------------------------------------------------------------------------------

def handoff_at(rotation, local_date):
    """The UTC instant of the handoff on `local_date`: `handoff_time` on the rotation's local clock.

    Across DST this moves in UTC (09:00 Dublin is 09:00 UTC in winter, 08:00 UTC in summer). On the night the
    clocks go back, a time that happens twice means the first one; a time skipped when they go forward means
    that wall time on the old offset, i.e. an hour later on the new clock.
    """
    local = datetime.combine(local_date, rotation.handoff_time, tzinfo=ZoneInfo(rotation.time_zone))
    return local.astimezone(UTC)


def shift_at(rotation, at):
    """The Shift covering instant `at`, or None before the rotation's first handoff."""
    at = at.astimezone(UTC)
    day = at.astimezone(ZoneInfo(rotation.time_zone)).date()
    if at < handoff_at(rotation, day):
        day -= timedelta(days=1)
    days_in = (day - rotation.start_date).days
    if days_in < 0:
        return None
    index = days_in // rotation.shift_length_days
    first_day = rotation.start_date + timedelta(days=index * rotation.shift_length_days)
    next_day = first_day + timedelta(days=rotation.shift_length_days)
    return Shift(index, first_day, handoff_at(rotation, first_day), handoff_at(rotation, next_day))


def rotation_user_at(rotation, at):
    """Whose turn it is on `rotation` at `at` (None before it starts or when it has no participants)."""
    participants = list(rotation.participants.all())
    shift = shift_at(rotation, at)
    if shift is None or not participants:
        return None
    return participants[shift.index % len(participants)].user


def handoffs_between(rotation, start, end):
    """Every handoff instant of `rotation` strictly after `start` and before `end`."""
    shift = shift_at(rotation, start)
    day = rotation.start_date if shift is None else shift.first_day + timedelta(days=rotation.shift_length_days)
    handoffs = []
    for _ in range(MAX_HANDOFFS):
        moment = handoff_at(rotation, day)
        if moment >= end:
            break
        if moment > start:
            handoffs.append(moment)
        day += timedelta(days=rotation.shift_length_days)
    return handoffs


# Who is on call --------------------------------------------------------------------------------------------------

def _covering_override(overrides, at):
    """The override in force at `at`; when several overlap, the most recently created one wins."""
    winner = None
    for override in overrides:
        if override.starts_at <= at < override.ends_at:
            if winner is None or (override.created_at, override.pk) > (winner.created_at, winner.pk):
                winner = override
    return winner


def _resolve(rotations, overrides, at):
    """(user, source) at `at` from already-loaded rotations (highest priority first) and overrides."""
    override = _covering_override(overrides, at)
    if override is not None:
        return override.user, 'override'
    for rotation in rotations:
        user = rotation_user_at(rotation, at)
        if user is not None:
            return user, rotation.name
    return None, ''


def _rotations(schedule):
    return list(schedule.rotations.prefetch_related('participants__user'))


def who_is_on_call(schedule, at=None):
    """The user on call for `schedule` at instant `at` (default: now), or None when nobody is.

    An override covering `at` wins; otherwise the highest-priority rotation that has started decides.
    """
    at = at or timezone.now()
    overrides = schedule.overrides.filter(starts_at__lte=at, ends_at__gt=at).select_related('user')
    user, _ = _resolve(_rotations(schedule), list(overrides), at)
    return user


def final_schedule(schedule, start, end):
    """Who is on call between `start` and `end`, as Segments with identical neighbours merged."""
    rotations = _rotations(schedule)
    overrides = list(schedule.overrides.filter(starts_at__lt=end, ends_at__gt=start).select_related('user'))
    boundaries = {start, end}
    for rotation in rotations:
        boundaries.update(handoffs_between(rotation, start, end))
    for override in overrides:
        for moment in (override.starts_at, override.ends_at):
            if start < moment < end:
                boundaries.add(moment)
    points = sorted(boundaries)

    segments = []
    for segment_start, segment_end in zip(points, points[1:]):
        user, source = _resolve(rotations, overrides, segment_start)
        previous = segments[-1] if segments else None
        if previous and previous.user == user and previous.source == source:
            segments[-1] = previous._replace(ends_at=segment_end)
        else:
            segments.append(Segment(segment_start, segment_end, user, source))
    return segments


def on_call_now(schedule, now=None, horizon_days=MAX_OVERRIDE_DAYS):
    """The current Segment (who is on call and until when), or None if nobody is on call right now."""
    now = now or timezone.now()
    segments = final_schedule(schedule, now, now + timedelta(days=horizon_days))
    if not segments or segments[0].user is None:
        return None
    return segments[0]


# Changing schedules ----------------------------------------------------------------------------------------------

def create_schedule(team, actor, name, description=''):
    require_role(team, actor, Role.ADMIN, 'create schedules')
    if Schedule.objects.filter(team=team, name__iexact=name.strip()).exists():
        raise OnCallError('This team already has a schedule with that name.')
    return Schedule.objects.create(team=team, name=name.strip(), description=description)


def _check_participants(team, participants):
    if not participants:
        raise OnCallError('A rotation needs at least one participant.')
    for user in participants:
        if not is_member(team, user):
            raise OnCallError(f'{user.username} is not a member of {team.name}.')


def save_rotation(schedule, actor, participants, rotation=None, **fields):
    """Create a rotation (or update `rotation`) with `participants` taking turns in the given order."""
    require_role(schedule.team, actor, Role.ADMIN, 'change rotations')
    _check_participants(schedule.team, participants)
    with transaction.atomic():
        if rotation is None:
            rotation = Rotation(schedule=schedule)
        for name, value in fields.items():
            setattr(rotation, name, value)
        rotation.full_clean(exclude=['schedule'])
        rotation.save()
        rotation.participants.all().delete()
        for position, user in enumerate(participants):
            RotationParticipant.objects.create(rotation=rotation, user=user, position=position)
    return rotation


def delete_rotation(rotation, actor):
    require_role(rotation.schedule.team, actor, Role.ADMIN, 'delete rotations')
    rotation.delete()


def create_override(schedule, actor, user, starts_at, ends_at, reason=''):
    """Put `user` on call from `starts_at` to `ends_at`. Responders may only cover shifts themselves."""
    team = schedule.team
    require_role(team, actor, Role.RESPONDER, 'create overrides')
    if user.pk != actor.pk and not has_role(team, actor, Role.ADMIN):
        raise OnCallError('Responders can only create overrides for themselves.')
    if not is_member(team, user):
        raise OnCallError(f'{user.username} is not a member of {team.name}.')
    if ends_at <= starts_at:
        raise OnCallError('The override must end after it starts.')
    if ends_at <= timezone.now():
        raise OnCallError('The override is entirely in the past.')
    if ends_at - starts_at > timedelta(days=MAX_OVERRIDE_DAYS):
        raise OnCallError(f'Overrides can last at most {MAX_OVERRIDE_DAYS} days.')
    return Override.objects.create(
        schedule=schedule, user=user, starts_at=starts_at, ends_at=ends_at, reason=reason, created_by=actor,
    )


def delete_override(override, actor):
    team = override.schedule.team
    if actor.pk not in (override.user_id, override.created_by_id) and not has_role(team, actor, Role.ADMIN):
        raise OnCallError('Only the person covering, whoever created it, or a team admin can delete this override.')
    override.delete()


def upcoming_overrides(schedule, now=None):
    now = now or timezone.now()
    return schedule.overrides.filter(ends_at__gt=now).select_related('user', 'created_by')
