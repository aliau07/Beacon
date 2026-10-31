from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.incidents.models import Incident
from apps.teams.shortcuts import get_for_member_or_404

from . import services
from .forms import ActionItemForm, EventForm, PostmortemForm, ScreenshotForm
from .models import ActionItem, Postmortem, Screenshot

POSTMORTEMS = Postmortem.objects.select_related('incident__team', 'incident__service', 'created_by')


def _get(request, pk):
    return get_for_member_or_404(POSTMORTEMS, request.user, 'incident__team', pk=pk)


@login_required
@require_POST
def start(request, incident_id):
    incident = get_for_member_or_404(Incident.objects.select_related('team', 'service'), request.user, pk=incident_id)
    try:
        postmortem = services.start_postmortem(incident, request.user)
    except services.PostmortemError as error:
        messages.error(request, str(error))
        return redirect(incident)
    messages.success(request, 'Postmortem started with the incident timeline filled in.')
    return redirect('postmortems:edit', postmortem.pk)


def _render(request, postmortem, template, **forms):
    team = postmortem.incident.team
    context = {
        'postmortem': postmortem,
        'incident': postmortem.incident,
        'team': team,
        'events': postmortem.events.all(),
        'action_items': postmortem.action_items.select_related('owner'),
        'screenshots': postmortem.screenshots.all(),
        'form': forms.get('form') or PostmortemForm(instance=postmortem),
        'event_form': forms.get('event_form') or EventForm(),
        'action_form': forms.get('action_form') or ActionItemForm(team=team),
        'screenshot_form': forms.get('screenshot_form') or ScreenshotForm(),
    }
    return render(request, template, context)


@login_required
def detail(request, pk):
    return _render(request, _get(request, pk), 'postmortems/detail.html')


@login_required
def edit(request, pk):
    postmortem = _get(request, pk)
    form = PostmortemForm(request.POST or None, instance=postmortem)
    if request.method == 'POST' and form.is_valid():
        services.update_postmortem(postmortem, request.user, **form.cleaned_data)
        messages.success(request, 'Postmortem saved.')
        return redirect(postmortem)
    return _render(request, postmortem, 'postmortems/edit.html', form=form)


@login_required
@require_POST
def publish(request, pk):
    postmortem = _get(request, pk)
    try:
        services.publish(postmortem, request.user)
    except services.PostmortemError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Postmortem published.')
    return redirect(postmortem)


@login_required
@require_POST
def event_add(request, pk):
    postmortem = _get(request, pk)
    form = EventForm(request.POST)
    if form.is_valid():
        services.add_event(postmortem, request.user, **form.cleaned_data)
        messages.success(request, 'Timeline entry added.')
        return redirect('postmortems:edit', postmortem.pk)
    return _render(request, postmortem, 'postmortems/edit.html', event_form=form)


@login_required
@require_POST
def action_add(request, pk):
    postmortem = _get(request, pk)
    form = ActionItemForm(request.POST, team=postmortem.incident.team)
    if form.is_valid():
        try:
            services.add_action_item(postmortem, request.user, **form.cleaned_data)
        except services.PostmortemError as error:
            form.add_error('owner', str(error))
        else:
            messages.success(request, 'Action item added.')
            return redirect(postmortem)
    return _render(request, postmortem, 'postmortems/detail.html', action_form=form)


@login_required
@require_POST
def action_toggle(request, pk):
    item = get_for_member_or_404(ActionItem.objects.select_related('postmortem__incident__team'), request.user,
                                 'postmortem__incident__team', pk=pk)
    services.toggle_action_item(item, request.user)
    return redirect(item.postmortem)


@login_required
@require_POST
def screenshot_add(request, pk):
    postmortem = _get(request, pk)
    form = ScreenshotForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.add_screenshot(postmortem, request.user, form.cleaned_data['image'], form.cleaned_data['caption'])
        except services.PostmortemError as error:
            form.add_error('image', str(error))
        else:
            messages.success(request, 'Screenshot added.')
            return redirect(postmortem)
    return _render(request, postmortem, 'postmortems/detail.html', screenshot_form=form)


@login_required
@require_POST
def screenshot_delete(request, pk):
    screenshot = get_for_member_or_404(Screenshot.objects.select_related('postmortem__incident__team'), request.user,
                                       'postmortem__incident__team', pk=pk)
    services.delete_screenshot(screenshot, request.user)
    messages.success(request, 'Screenshot removed.')
    return redirect(screenshot.postmortem)
