from django import forms

from apps.core.forms import BootstrapFormMixin
from apps.teams.services import members

from .models import EscalationPolicy


class PolicyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = EscalationPolicy
        fields = ['name', 'description', 'repeat_count']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def validate_unique(self):
        """Name clashes are checked by the service (the form has no team field)."""


class LevelForm(BootstrapFormMixin, forms.Form):
    target_user = forms.ModelChoiceField(queryset=None, required=False, label='Page this person')
    target_schedule = forms.ModelChoiceField(queryset=None, required=False, label='or whoever is on call for')
    delay_minutes = forms.IntegerField(min_value=1, max_value=24 * 60, initial=15,
                                       help_text='Minutes to wait for an acknowledgement before the next level.')

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['target_user'].queryset = members(team)
        self.fields['target_schedule'].queryset = team.schedules.all()

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get('target_user') is None) == (cleaned.get('target_schedule') is None):
            raise forms.ValidationError('Choose either a person or a schedule.')
        return cleaned
