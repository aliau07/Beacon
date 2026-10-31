from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.teams.services import Role, has_role, require_role
from apps.teams.shortcuts import get_for_member_or_404, get_team_or_404

from . import services
from .forms import LevelForm, PolicyForm
from .models import EscalationLevel, EscalationPolicy


@login_required
def policy_list(request, team_slug):
    team = get_team_or_404(request.user, team_slug)
    return render(request, 'escalation/policy_list.html', {
        'team': team,
        'policies': team.escalation_policies.prefetch_related('levels__target_user', 'levels__target_schedule', 'services'),
        'can_manage': has_role(team, request.user, Role.ADMIN),
    })


@login_required
def policy_create(request, team_slug):
    team = get_team_or_404(request.user, team_slug, Role.ADMIN, 'create escalation policies')
    form = PolicyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            policy = services.create_policy(team, request.user, **form.cleaned_data)
        except services.EscalationError as error:
            form.add_error('name', str(error))
        else:
            messages.success(request, f'{policy.name} created. Add its first level below.')
            return redirect(policy)
    return render(request, 'escalation/policy_form.html', {'team': team, 'form': form})


@login_required
def policy_detail(request, pk):
    policy = get_for_member_or_404(EscalationPolicy.objects.select_related('team'), request.user, pk=pk)
    can_manage = has_role(policy.team, request.user, Role.ADMIN)
    form = PolicyForm(request.POST or None, instance=policy)
    if request.method == 'POST':
        require_role(policy.team, request.user, Role.ADMIN, 'change escalation policies')
        if form.is_valid():
            try:
                services.update_policy(policy, request.user, **form.cleaned_data)
            except services.EscalationError as error:
                form.add_error('name', str(error))
            else:
                messages.success(request, 'Escalation policy saved.')
                return redirect(policy)
    return render(request, 'escalation/policy_detail.html', {
        'team': policy.team,
        'policy': policy,
        'levels': policy.levels.select_related('target_user', 'target_schedule'),
        'form': form,
        'level_form': LevelForm(team=policy.team),
        'can_manage': can_manage,
    })


@login_required
@require_POST
def level_add(request, policy_id):
    policy = get_for_member_or_404(EscalationPolicy.objects.select_related('team'), request.user, pk=policy_id)
    form = LevelForm(request.POST, team=policy.team)
    if not form.is_valid():
        for error in form.non_field_errors():
            messages.error(request, error)
        if not form.non_field_errors():
            messages.error(request, 'Check the level: the delay must be between 1 and 1440 minutes.')
        return redirect(policy)
    try:
        services.add_level(policy, request.user, **form.cleaned_data)
    except services.EscalationError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Level added.')
    return redirect(policy)


@login_required
@require_POST
def level_delete(request, pk):
    level = get_for_member_or_404(EscalationLevel.objects.select_related('policy__team'), request.user, 'policy__team', pk=pk)
    services.remove_level(level, request.user)
    messages.success(request, 'Level removed.')
    return redirect(level.policy)
