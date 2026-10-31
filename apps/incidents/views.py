from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.teams.services import teams_for
from apps.teams.shortcuts import get_for_member_or_404, get_team_or_404

from . import services
from .forms import IncidentFilterForm, ManualIncidentForm, NoteForm
from .models import Incident


@login_required
def incident_list(request):
    teams = list(teams_for(request.user))
    form = IncidentFilterForm(request.GET or None, teams=teams)
    incidents = form.filter(services.incidents_for(request.user))
    page = Paginator(incidents, 25).get_page(request.GET.get('page'))
    return render(request, 'incidents/list.html', {'form': form, 'page_obj': page, 'incidents': page.object_list,
                                                   'teams': teams})


@login_required
def incident_create(request, team_slug):
    team = get_team_or_404(request.user, team_slug)
    form = ManualIncidentForm(request.POST or None, team=team)
    if request.method == 'POST' and form.is_valid():
        incident, _ = services.trigger(
            form.cleaned_data['service'], form.cleaned_data['summary'], form.cleaned_data['severity'],
            source=Incident.Source.WEB, actor=request.user,
        )
        messages.success(request, f'Incident #{incident.pk} triggered. The escalation policy is paging people now.')
        return redirect(incident)
    return render(request, 'incidents/form.html', {'team': team, 'form': form})


def _get_incident(request, pk):
    return get_for_member_or_404(Incident.objects.select_related('team', 'service', 'acknowledged_by', 'resolved_by'),
                                 request.user, pk=pk)


@login_required
def incident_detail(request, pk):
    incident = _get_incident(request, pk)
    return render(request, 'incidents/detail.html', {
        'incident': incident,
        'team': incident.team,
        'timeline': services.timeline_for(incident),
        'alerts': incident.alerts.all()[:20],
        'note_form': NoteForm(),
        'can_acknowledge': services.can_transition(incident, Incident.Status.ACKNOWLEDGED),
        'can_resolve': services.can_transition(incident, Incident.Status.RESOLVED),
    })


ACTIONS = {
    'acknowledge': (services.acknowledge, 'Incident acknowledged. Escalation has stopped.'),
    'resolve': (services.resolve, 'Incident resolved.'),
}


@login_required
@require_POST
def incident_action(request, pk, action):
    incident = _get_incident(request, pk)
    change, success_message = ACTIONS[action]
    try:
        change(incident, request.user, via='Beacon')
    except services.IncidentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, success_message)
    return redirect(incident)


@login_required
@require_POST
def note_add(request, pk):
    incident = _get_incident(request, pk)
    try:
        services.add_note(incident, request.user, request.POST.get('text', ''))
    except services.IncidentError as error:
        messages.error(request, str(error))
    return redirect(incident)
