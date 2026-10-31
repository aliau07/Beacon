from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.teams.services import Role, has_role, require_role
from apps.teams.shortcuts import get_for_member_or_404, get_team_or_404

from . import services
from .forms import ApiKeyForm, ServiceForm
from .models import ApiKey, Service


@login_required
def service_list(request, team_slug):
    team = get_team_or_404(request.user, team_slug)
    return render(request, 'services/list.html', {
        'team': team,
        'services': team.services.select_related('escalation_policy'),
        'can_manage': has_role(team, request.user, Role.ADMIN),
    })


@login_required
def service_create(request, team_slug):
    team = get_team_or_404(request.user, team_slug, Role.ADMIN, 'create services')
    form = ServiceForm(request.POST or None, team=team)
    if request.method == 'POST' and form.is_valid():
        try:
            service = services.create_service(team, request.user, **form.cleaned_data)
        except services.ServiceError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f'{service.name} created. Create an API key to start sending events.')
            return redirect(service)
    return render(request, 'services/form.html', {'team': team, 'form': form})


@login_required
def service_edit(request, pk):
    service = get_for_member_or_404(Service.objects.select_related('team'), request.user, pk=pk)
    require_role(service.team, request.user, Role.ADMIN, 'change services')
    form = ServiceForm(request.POST or None, instance=service, team=service.team)
    if request.method == 'POST' and form.is_valid():
        try:
            services.update_service(service, request.user, **form.cleaned_data)
        except services.ServiceError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, 'Service saved.')
            return redirect(service)
    return render(request, 'services/form.html', {'team': service.team, 'form': form, 'service': service})


def _detail(request, service, **extra):
    return render(request, 'services/detail.html', {
        'team': service.team,
        'service': service,
        'api_keys': service.api_keys.select_related('created_by'),
        'open_incidents': service.incidents.filter(status__in=['triggered', 'acknowledged']),
        'recent_incidents': service.incidents.filter(status='resolved')[:10],
        'can_manage': has_role(service.team, request.user, Role.ADMIN),
        'key_form': ApiKeyForm(),
        **extra,
    })


@login_required
def service_detail(request, pk):
    service = get_for_member_or_404(Service.objects.select_related('team', 'escalation_policy'), request.user, pk=pk)
    return _detail(request, service)


@never_cache
@login_required
@require_POST
def api_key_create(request, pk):
    """Create a key and show it in this response only. It is not stored, so it can't be shown again."""
    service = get_for_member_or_404(Service.objects.select_related('team', 'escalation_policy'), request.user, pk=pk)
    form = ApiKeyForm(request.POST)
    if not form.is_valid():
        return _detail(request, service, key_form=form)
    api_key, raw_key = services.create_api_key(service, request.user, form.cleaned_data['name'])
    return _detail(request, service, new_key=api_key, new_raw_key=raw_key)


@login_required
@require_POST
def api_key_revoke(request, pk):
    api_key = get_for_member_or_404(ApiKey.objects.select_related('service__team'), request.user, 'service__team', pk=pk)
    services.revoke_api_key(api_key, request.user)
    messages.success(request, f'API key {api_key.prefix}… revoked. Events sent with it are now rejected.')
    return redirect(api_key.service)
