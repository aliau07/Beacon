"""Teams and their members. Owners run the team, admins manage its setup (services, schedules, escalation, status
page), responders handle incidents. Every other app asks this module who may do what."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.text import slugify

from apps.core.notifications import notify

from .models import Membership, Team

Role = Membership.Role
ROLE_RANK = {Role.RESPONDER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class TeamError(Exception):
    """A membership change that breaks the rules, e.g. removing the last owner."""


class TeamPermissionDenied(PermissionDenied):
    """The user's role in the team is too low for the action (shown as a 403 page)."""


def teams_for(user):
    if not getattr(user, 'is_authenticated', False):
        return Team.objects.none()
    return Team.objects.filter(memberships__user=user)


def membership_for(team, user):
    if not getattr(user, 'is_authenticated', False):
        return None
    return Membership.objects.filter(team=team, user=user).first()


def role_for(team, user):
    membership = membership_for(team, user)
    return membership.role if membership else None


def has_role(team, user, minimum=Role.RESPONDER):
    role = role_for(team, user)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[minimum]


def is_member(team, user):
    return has_role(team, user, Role.RESPONDER)


def require_role(team, user, minimum, action='do that'):
    if not has_role(team, user, minimum):
        raise TeamPermissionDenied(f'You need to be a team {Role(minimum).label.lower()} or above to {action}.')


def members(team):
    """The team's users, alphabetically."""
    return get_user_model().objects.filter(memberships__team=team).order_by('username')


def memberships(team):
    return team.memberships.select_related('user').order_by('user__username')


def _unique_slug(name):
    base = slugify(name)[:100] or 'team'
    slug, n = base, 2
    while Team.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


def create_team(name, owner):
    name = name.strip()
    if Team.objects.filter(name__iexact=name).exists():
        raise TeamError('A team with this name already exists.')
    with transaction.atomic():
        team = Team.objects.create(name=name, slug=_unique_slug(name))
        Membership.objects.create(team=team, user=owner, role=Role.OWNER)
    return team


def _lock(team):
    """Serialise membership changes per team so two admins can't both remove 'the other' last owner."""
    Team.objects.select_for_update().get(pk=team.pk)


def _owner_count(team):
    return Membership.objects.filter(team=team, role=Role.OWNER).count()


def add_member(team, actor, user, role=Role.RESPONDER):
    require_role(team, actor, Role.ADMIN, 'add members')
    if role == Role.OWNER:
        require_role(team, actor, Role.OWNER, 'add owners')
    with transaction.atomic():
        _lock(team)
        if Membership.objects.filter(team=team, user=user).exists():
            raise TeamError(f'{user.username} is already a member of {team.name}.')
        membership = Membership.objects.create(team=team, user=user, role=role)
    notify(user, f'You were added to {team.name}', 'teams/emails/added.txt', {
        'team': team, 'membership': membership, 'actor': actor, 'team_path': team.get_absolute_url(),
    })
    return membership


def change_role(team, actor, membership, role):
    require_role(team, actor, Role.ADMIN, 'change roles')
    if Role.OWNER in (role, membership.role):
        require_role(team, actor, Role.OWNER, 'grant or remove the owner role')
    with transaction.atomic():
        _lock(team)
        membership.refresh_from_db()
        if membership.role == Role.OWNER and role != Role.OWNER and _owner_count(team) == 1:
            raise TeamError('A team needs at least one owner. Make someone else an owner first.')
        membership.role = role
        membership.save(update_fields=['role'])
    return membership


def remove_member(team, actor, membership):
    """Admins remove members (owners remove owners); anyone may leave. The last owner can't go."""
    if membership.user_id != actor.pk:
        require_role(team, actor, Role.ADMIN, 'remove members')
        if membership.role == Role.OWNER:
            require_role(team, actor, Role.OWNER, 'remove an owner')
    with transaction.atomic():
        _lock(team)
        membership.refresh_from_db()
        if membership.role == Role.OWNER and _owner_count(team) == 1:
            raise TeamError('A team needs at least one owner. Make someone else an owner first.')
        membership.delete()
