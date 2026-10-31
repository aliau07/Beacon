import re

from django import forms

from apps.core.forms import BootstrapFormMixin
from apps.core.validators import time_zone_choices
from apps.teams.services import members

from .models import Rotation

DATETIME_INPUT = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')


class ScheduleForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(max_length=100)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class RotationForm(BootstrapFormMixin, forms.ModelForm):
    time_zone = forms.ChoiceField(choices=time_zone_choices)
    participant_names = forms.CharField(
        label='Participants', widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Usernames in rotation order, separated by commas or new lines. Someone can appear more than once.',
    )

    class Meta:
        model = Rotation
        fields = ['name', 'time_zone', 'start_date', 'handoff_time', 'shift_length_days', 'priority']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'handoff_time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        if self.instance.pk:
            usernames = []
            for participant in self.instance.participants.select_related('user'):
                usernames.append(participant.user.username)
            self.initial['participant_names'] = ', '.join(usernames)

    def clean_participant_names(self):
        team_members = {}
        for user in members(self.team):
            team_members[user.username.lower()] = user
        participants, unknown = [], []
        for name in re.split(r'[\s,]+', self.cleaned_data['participant_names']):
            if not name:
                continue
            user = team_members.get(name.lower())
            if user is None:
                unknown.append(name)
            else:
                participants.append(user)
        if unknown:
            raise forms.ValidationError(f"Not on {self.team.name}: {', '.join(unknown)}.")
        if not participants:
            raise forms.ValidationError('Add at least one participant.')
        return participants


class OverrideForm(BootstrapFormMixin, forms.Form):
    user = forms.ModelChoiceField(queryset=None, label='Who is on call')
    starts_at = forms.DateTimeField(widget=DATETIME_INPUT, help_text='In your time zone.')
    ends_at = forms.DateTimeField(widget=DATETIME_INPUT)
    reason = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = members(team)
