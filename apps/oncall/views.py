from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.teams.services import Role, has_role, require_role, teams_for
from apps.teams.shortcuts import get_for_member_or_404, get_team_or_404

from . import services
from .forms import OverrideForm, RotationForm, ScheduleForm
from .models import Override, Rotation, Schedule

PREVIEW_DAYS = 14


@login_required
def now(request):
    """Who is on call right now for every schedule of every team the user is on."""
    rows = []
    schedules = Schedule.objects.filter(team__in=teams_for(request.user)).select_related('team').order_by('team__name', 'name')
    for schedule in schedules:
        rows.append((schedule, services.on_call_now(schedule)))
    return render(request, 'oncall/now.html', {'rows': rows})


@login_required
def schedule_list(request, team_slug):
    team = get_team_or_404(request.user, team_slug)
    rows = []
    for schedule in team.schedules.all():
        rows.append((schedule, services.on_call_now(schedule)))
    return render(request, 'oncall/schedule_list.html', {
        'team': team, 'rows': rows, 'can_manage': has_role(team, request.user, Role.ADMIN),
    })


@login_required
def schedule_create(request, team_slug):
    team = get_team_or_404(request.user, team_slug, Role.ADMIN, 'create schedules')
    form = ScheduleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            schedule = services.create_schedule(team, request.user, **form.cleaned_data)
        except services.OnCallError as error:
            form.add_error('name', str(error))
        else:
            messages.success(request, f'{schedule.name} created. Add a rotation to put people on call.')
            return redirect(schedule)
    return render(request, 'oncall/schedule_form.html', {'team': team, 'form': form})


@login_required
def schedule_detail(request, pk):
    schedule = get_for_member_or_404(Schedule.objects.select_related('team'), request.user, pk=pk)
    team = schedule.team
    start = timezone.now()
    return render(request, 'oncall/schedule_detail.html', {
        'team': team,
        'schedule': schedule,
        'current': services.on_call_now(schedule, start),
        'segments': services.final_schedule(schedule, start, start + timedelta(days=PREVIEW_DAYS)),
        'preview_days': PREVIEW_DAYS,
        'rotations': schedule.rotations.prefetch_related('participants__user'),
        'overrides': services.upcoming_overrides(schedule, start),
        'override_form': OverrideForm(team=team, initial={'user': request.user}),
        'can_manage': has_role(team, request.user, Role.ADMIN),
    })


@login_required
def rotation_form(request, schedule_id=None, pk=None):
    """Add a rotation to a schedule, or edit one."""
    if pk is not None:
        rotation = get_for_member_or_404(Rotation.objects.select_related('schedule__team'), request.user, 'schedule__team', pk=pk)
        schedule = rotation.schedule
    else:
        rotation = None
        schedule = get_for_member_or_404(Schedule.objects.select_related('team'), request.user, pk=schedule_id)
    require_role(schedule.team, request.user, Role.ADMIN, 'change rotations')
    initial = {'time_zone': request.user.time_zone, 'start_date': timezone.localdate()}
    form = RotationForm(request.POST or None, instance=rotation, team=schedule.team, initial=initial)
    if request.method == 'POST' and form.is_valid():
        fields = {}
        for name in RotationForm.Meta.fields:
            fields[name] = form.cleaned_data[name]
        try:
            services.save_rotation(schedule, request.user, form.cleaned_data['participant_names'], rotation, **fields)
        except services.OnCallError as error:
            form.add_error('participant_names', str(error))
        else:
            messages.success(request, 'Rotation saved.')
            return redirect(schedule)
    return render(request, 'oncall/rotation_form.html', {'team': schedule.team, 'schedule': schedule, 'form': form,
                                                         'rotation': rotation})


@login_required
@require_POST
def rotation_delete(request, pk):
    rotation = get_for_member_or_404(Rotation.objects.select_related('schedule__team'), request.user, 'schedule__team', pk=pk)
    services.delete_rotation(rotation, request.user)
    messages.success(request, f'Rotation {rotation.name} deleted.')
    return redirect(rotation.schedule)


@login_required
@require_POST
def override_create(request, schedule_id):
    schedule = get_for_member_or_404(Schedule.objects.select_related('team'), request.user, pk=schedule_id)
    form = OverrideForm(request.POST, team=schedule.team)
    if not form.is_valid():
        messages.error(request, 'Choose who is on call and when the override starts and ends.')
        return redirect(schedule)
    try:
        services.create_override(schedule, request.user, **form.cleaned_data)
    except services.OnCallError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Override added.')
    return redirect(schedule)


@login_required
@require_POST
def override_delete(request, pk):
    override = get_for_member_or_404(Override.objects.select_related('schedule__team'), request.user, 'schedule__team', pk=pk)
    try:
        services.delete_override(override, request.user)
    except services.OnCallError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Override removed.')
    return redirect(override.schedule)
