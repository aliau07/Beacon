"""Escalation: page level 1 when an incident triggers, then page the next level whenever a level's delay passes
without an acknowledgement, repeating the policy `repeat_count` times.

`run_due` is driven by `manage.py run_escalations` (cron, every minute). Each incident is escalated in its own
transaction with SELECT ... FOR UPDATE SKIP LOCKED, so several workers can run at once without paging twice.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.incidents.models import Incident, TimelineEntry
from apps.incidents.services import add_timeline_entry
from apps.notifications.services import page
from apps.oncall.services import who_is_on_call
from apps.teams.services import Role, is_member, require_role

from .models import EscalationLevel, EscalationPolicy, EscalationState

BATCH_LIMIT = 500


class EscalationError(Exception):
    """A policy change that breaks the rules, e.g. a level whose target isn't on the team."""


# Policies --------------------------------------------------------------------------------------------------------

def create_policy(team, actor, name, description='', repeat_count=0):
    require_role(team, actor, Role.ADMIN, 'create escalation policies')
    if EscalationPolicy.objects.filter(team=team, name__iexact=name.strip()).exists():
        raise EscalationError('This team already has an escalation policy with that name.')
    return EscalationPolicy.objects.create(team=team, name=name.strip(), description=description, repeat_count=repeat_count)


def update_policy(policy, actor, name, description='', repeat_count=0):
    require_role(policy.team, actor, Role.ADMIN, 'change escalation policies')
    clash = EscalationPolicy.objects.filter(team=policy.team, name__iexact=name.strip()).exclude(pk=policy.pk)
    if clash.exists():
        raise EscalationError('This team already has an escalation policy with that name.')
    policy.name, policy.description, policy.repeat_count = name.strip(), description, repeat_count
    policy.save(update_fields=['name', 'description', 'repeat_count'])
    return policy


def add_level(policy, actor, delay_minutes, target_user=None, target_schedule=None):
    team = policy.team
    require_role(team, actor, Role.ADMIN, 'change escalation policies')
    if (target_user is None) == (target_schedule is None):
        raise EscalationError('Choose either a person or a schedule to page.')
    if target_user is not None and not is_member(team, target_user):
        raise EscalationError(f'{target_user.username} is not a member of {team.name}.')
    if target_schedule is not None and target_schedule.team_id != team.pk:
        raise EscalationError("That schedule belongs to another team.")
    with transaction.atomic():
        EscalationPolicy.objects.select_for_update().get(pk=policy.pk)
        last = policy.levels.aggregate(last=Max('position'))['last']
        return EscalationLevel.objects.create(
            policy=policy, position=0 if last is None else last + 1, delay_minutes=delay_minutes,
            target_user=target_user, target_schedule=target_schedule,
        )


def remove_level(level, actor):
    policy = level.policy
    require_role(policy.team, actor, Role.ADMIN, 'change escalation policies')
    with transaction.atomic():
        EscalationPolicy.objects.select_for_update().get(pk=policy.pk)
        level.delete()
        for position, remaining in enumerate(policy.levels.order_by('position')):
            if remaining.position != position:
                remaining.position = position
                remaining.save(update_fields=['position'])


# Running escalations ---------------------------------------------------------------------------------------------

def _levels(policy):
    return list(policy.levels.select_related('target_user', 'target_schedule__team'))


def _page_level(incident, policy, level, cycle, now):
    """Page the level's target and note it on the timeline. Returns the user paged, or None."""
    label = f'level {level.number}' + (f', repeat {cycle}' if cycle else '')
    if level.target_schedule_id:
        user = who_is_on_call(level.target_schedule, now)
        via = f' via {level.target_schedule.name}'
        if user is None:
            add_timeline_entry(incident, TimelineEntry.Kind.PAGED, f'Nobody is on call for {level.target_schedule.name} ({label}).')
            return None
    else:
        user, via = level.target_user, ''
    if not is_member(incident.team, user):
        add_timeline_entry(incident, TimelineEntry.Kind.PAGED, f'Skipped {user.display_name}: no longer on {incident.team.name} ({label}).')
        return None
    page(user, incident, f'{policy.name}, {label}{via}')
    add_timeline_entry(incident, TimelineEntry.Kind.PAGED, f'Paged {user.display_name} ({label}{via}).')
    return user


def start(incident):
    """Page level 1 of the service's policy for a newly triggered incident and schedule level 2."""
    if not Incident.objects.filter(pk=incident.pk, status=Incident.Status.TRIGGERED).exists():
        return None  # acknowledged or resolved before this after-commit receiver ran
    policy = incident.service.escalation_policy
    if policy is None:
        add_timeline_entry(incident, TimelineEntry.Kind.PAGED, 'The service has no escalation policy, so nobody was paged.')
        return None
    levels = _levels(policy)
    if not levels:
        add_timeline_entry(incident, TimelineEntry.Kind.PAGED, f'{policy.name} has no levels, so nobody was paged.')
        return None
    now = timezone.now()
    with transaction.atomic():
        state, created = EscalationState.objects.get_or_create(incident=incident, defaults={
            'policy': policy, 'next_run_at': now + timedelta(minutes=levels[0].delay_minutes),
        })
        if created:
            _page_level(incident, policy, levels[0], 0, now)
    return state


def stop(incident):
    """Nothing more to page: the incident was acknowledged or resolved."""
    EscalationState.objects.filter(incident=incident, next_run_at__isnull=False).update(next_run_at=None, updated_at=timezone.now())


def _advance(state, now):
    """Page the next level for one due state (already locked). Returns whether someone new was paged or tried."""
    incident = Incident.objects.select_for_update().get(pk=state.incident_id)
    levels = _levels(state.policy)
    if incident.status != Incident.Status.TRIGGERED or not levels:
        state.next_run_at = None
        state.save(update_fields=['next_run_at', 'updated_at'])
        return False

    index, cycle = state.level_index + 1, state.cycle
    if index >= len(levels):
        if cycle >= state.policy.repeat_count:
            state.next_run_at = None
            state.save(update_fields=['next_run_at', 'updated_at'])
            rounds = state.policy.repeat_count + 1
            add_timeline_entry(incident, TimelineEntry.Kind.ESCALATED,
                               f'Escalation finished: nobody acknowledged after {rounds} round{"s" if rounds > 1 else ""} of {state.policy.name}.')
            return False
        index, cycle = 0, cycle + 1

    level = levels[index]
    state.level_index, state.cycle = index, cycle
    state.next_run_at = now + timedelta(minutes=level.delay_minutes)
    state.save(update_fields=['level_index', 'cycle', 'next_run_at', 'updated_at'])
    add_timeline_entry(incident, TimelineEntry.Kind.ESCALATED, f'Not acknowledged in time: escalated to level {level.number}.')
    _page_level(incident, state.policy, level, cycle, now)
    return True


def run_due(now=None, limit=BATCH_LIMIT):
    """Escalate every triggered incident whose current level has timed out. Returns how many were escalated."""
    now = now or timezone.now()
    escalated = 0
    for _ in range(limit):
        with transaction.atomic():
            # of=('self',): lock only the state row, not the shared policy row joined in by select_related.
            state = (EscalationState.objects.select_for_update(skip_locked=True, of=('self',))
                     .filter(next_run_at__lte=now).select_related('policy').order_by('next_run_at', 'pk').first())
            if state is None:
                break
            if _advance(state, now):
                escalated += 1
    return escalated
