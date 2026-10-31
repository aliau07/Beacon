from django import forms

from apps.core.choices import Severity
from apps.core.forms import BootstrapFormMixin

from .models import Incident

STATUS_FILTERS = [('open', 'Open'), ('triggered', 'Triggered'), ('acknowledged', 'Acknowledged'),
                  ('resolved', 'Resolved'), ('all', 'All')]


class IncidentFilterForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(choices=STATUS_FILTERS, required=False)
    team = forms.ChoiceField(required=False)
    severity = forms.ChoiceField(choices=[('', 'Any severity')] + Severity.choices, required=False)

    def __init__(self, *args, teams, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', 'All teams')]
        for team in teams:
            choices.append((team.slug, team.name))
        self.fields['team'].choices = choices

    def filter(self, incidents):
        data = self.cleaned_data if self.is_valid() else {}
        status = data.get('status') or 'open'
        if status == 'open':
            incidents = incidents.filter(status__in=Incident.OPEN_STATUSES)
        elif status != 'all':
            incidents = incidents.filter(status=status)
        if data.get('team'):
            incidents = incidents.filter(team__slug=data['team'])
        if data.get('severity'):
            incidents = incidents.filter(severity=data['severity'])
        return incidents


class ManualIncidentForm(BootstrapFormMixin, forms.Form):
    service = forms.ModelChoiceField(queryset=None)
    summary = forms.CharField(max_length=255)
    severity = forms.ChoiceField(choices=Severity.choices, initial=Severity.ERROR)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].queryset = team.services.all()


class NoteForm(BootstrapFormMixin, forms.Form):
    text = forms.CharField(label='Add a note', widget=forms.Textarea(attrs={'rows': 2}), max_length=5000)
