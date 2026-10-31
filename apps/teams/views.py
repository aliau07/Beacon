from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.services import find_user

from . import services
from .forms import AddMemberForm, RoleForm, TeamForm
from .models import Membership
from .shortcuts import get_team_or_404


@login_required
def team_list(request):
    teams = services.teams_for(request.user).prefetch_related('memberships')
    return render(request, 'teams/list.html', {'teams': teams})


@login_required
def team_create(request):
    form = TeamForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            team = services.create_team(form.cleaned_data['name'], request.user)
        except services.TeamError as error:
            form.add_error('name', str(error))
        else:
            messages.success(request, f'{team.name} created. You are its owner.')
            return redirect(team)
    return render(request, 'teams/form.html', {'form': form})


@login_required
def team_detail(request, slug):
    team = get_team_or_404(request.user, slug)
    role = services.role_for(team, request.user)
    return render(request, 'teams/detail.html', {
        'team': team,
        'role': role,
        'can_manage': services.has_role(team, request.user, services.Role.ADMIN),
        'is_owner': role == services.Role.OWNER,
        'memberships': services.memberships(team),
        'add_form': AddMemberForm(),
        'roles': Membership.Role.choices,
    })


@login_required
@require_POST
def member_add(request, slug):
    team = get_team_or_404(request.user, slug)
    form = AddMemberForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter a username or email address and a role.')
        return redirect(team)
    user = find_user(form.cleaned_data['identifier'])
    if user is None:
        messages.error(request, 'No Beacon account has that username or email. Ask them to sign up first.')
        return redirect(team)
    try:
        services.add_member(team, request.user, user, form.cleaned_data['role'])
    except services.TeamError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'{user.username} added to {team.name}.')
    return redirect(team)


@login_required
@require_POST
def member_role(request, slug, membership_id):
    team = get_team_or_404(request.user, slug)
    membership = get_object_or_404(Membership.objects.select_related('user'), team=team, pk=membership_id)
    form = RoleForm(request.POST)
    if form.is_valid():
        try:
            services.change_role(team, request.user, membership, form.cleaned_data['role'])
        except services.TeamError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f'{membership.user.username} is now a team {membership.get_role_display().lower()}.')
    return redirect(team)


@login_required
@require_POST
def member_remove(request, slug, membership_id):
    team = get_team_or_404(request.user, slug)
    membership = get_object_or_404(Membership.objects.select_related('user'), team=team, pk=membership_id)
    leaving = membership.user_id == request.user.pk
    try:
        services.remove_member(team, request.user, membership)
    except services.TeamError as error:
        messages.error(request, str(error))
        return redirect(team)
    if leaving:
        messages.success(request, f'You left {team.name}.')
        return redirect('teams:list')
    messages.success(request, f'{membership.user.username} removed from {team.name}.')
    return redirect(team)
