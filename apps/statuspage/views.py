from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.teams.services import Role, has_role, require_role
from apps.teams.shortcuts import get_for_member_or_404, get_team_or_404

from . import services
from .forms import ComponentForm, StatusPageForm
from .models import Component, StatusPage


@login_required
def manage(request, team_slug):
    team = get_team_or_404(request.user, team_slug)
    status_page = StatusPage.objects.filter(team=team).first()
    initial = {'title': f'{team.name} status', 'slug': team.slug}
    form = StatusPageForm(request.POST or None, instance=status_page, initial=initial)
    if request.method == 'POST':
        require_role(team, request.user, Role.ADMIN, 'change the status page')
        if form.is_valid():
            try:
                services.save_page(team, request.user, **form.cleaned_data)
            except services.StatusPageError as error:
                form.add_error('slug', str(error))
            else:
                messages.success(request, 'Status page saved.')
                return redirect('statuspage:manage', team.slug)
    return render(request, 'statuspage/manage.html', {
        'team': team,
        'status_page': status_page,
        'summary': services.summary(status_page) if status_page else None,
        'form': form,
        'component_form': ComponentForm(team=team),
        'can_manage': has_role(team, request.user, Role.ADMIN),
    })


def _save_component(request, status_page, form, component=None):
    data = form.cleaned_data
    return services.save_component(
        status_page, request.user, data['name'], list(data['services']), description=data['description'],
        position=data['position'] or 0, override_status=data['override_status'],
        override_message=data['override_message'], component=component,
    )


@login_required
@require_POST
def component_add(request, team_slug):
    team = get_team_or_404(request.user, team_slug, Role.ADMIN, 'change the status page')
    status_page = StatusPage.objects.filter(team=team).first()
    if status_page is None:
        raise Http404('Create the status page first.')
    form = ComponentForm(request.POST, team=team)
    if form.is_valid():
        try:
            _save_component(request, status_page, form)
        except services.StatusPageError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Component added.')
    else:
        messages.error(request, 'Give the component a name.')
    return redirect('statuspage:manage', team.slug)


@login_required
def component_edit(request, pk):
    component = get_for_member_or_404(Component.objects.select_related('status_page__team'), request.user,
                                      'status_page__team', pk=pk)
    team = component.status_page.team
    require_role(team, request.user, Role.ADMIN, 'change the status page')
    form = ComponentForm(request.POST or None, instance=component, team=team)
    if request.method == 'POST' and form.is_valid():
        try:
            _save_component(request, component.status_page, form, component)
        except services.StatusPageError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f'{component.name} saved.')
            return redirect('statuspage:manage', team.slug)
    return render(request, 'statuspage/component_form.html', {'team': team, 'component': component, 'form': form})


@login_required
@require_POST
def component_delete(request, pk):
    component = get_for_member_or_404(Component.objects.select_related('status_page__team'), request.user,
                                      'status_page__team', pk=pk)
    services.delete_component(component, request.user)
    messages.success(request, f'{component.name} removed from the status page.')
    return redirect('statuspage:manage', component.status_page.team.slug)


def public(request, slug):
    status_page = services.public_page(slug)
    if status_page is None:
        raise Http404('No such status page.')
    return render(request, 'statuspage/public.html', {'status_page': status_page, 'summary': services.summary(status_page)})


@never_cache
def public_summary(request, slug):
    status_page = services.public_page(slug)
    if status_page is None:
        return JsonResponse({'error': 'No such status page.'}, status=404)
    return JsonResponse(services.summary(status_page))
