"""View helpers every app uses to scope objects to the signed-in user's teams."""
from django.shortcuts import get_object_or_404

from .models import Team
from .services import require_role


def get_team_or_404(user, slug, minimum_role=None, action='do that'):
    """The team with `slug` if `user` belongs to it (404 otherwise, so outsiders can't probe team names).

    With `minimum_role`, members below that role get a 403.
    """
    team = get_object_or_404(Team, slug=slug, memberships__user=user)
    if minimum_role:
        require_role(team, user, minimum_role, action)
    return team


def get_for_member_or_404(queryset, user, team_path='team', **lookup):
    """An object that belongs to one of `user`'s teams, or 404. `team_path` is the lookup from the object to its team."""
    lookup[f'{team_path}__memberships__user'] = user
    return get_object_or_404(queryset, **lookup)
