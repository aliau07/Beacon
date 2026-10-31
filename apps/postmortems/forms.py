from django import forms

from apps.core.forms import BootstrapFormMixin
from apps.teams.services import members

from .models import Postmortem

DATETIME_INPUT = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')


class PostmortemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Postmortem
        fields = ['title', 'impact', 'root_cause']
        widgets = {'impact': forms.Textarea(attrs={'rows': 5}), 'root_cause': forms.Textarea(attrs={'rows': 5})}


class EventForm(BootstrapFormMixin, forms.Form):
    occurred_at = forms.DateTimeField(widget=DATETIME_INPUT, label='When')
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), max_length=2000)


class ActionItemForm(BootstrapFormMixin, forms.Form):
    description = forms.CharField(max_length=255, label='Action item')
    owner = forms.ModelChoiceField(queryset=None, required=False)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = members(team)


class ScreenshotForm(BootstrapFormMixin, forms.Form):
    image = forms.ImageField(help_text='Resized to fit 1600 px; photo metadata is removed.')
    caption = forms.CharField(max_length=200, required=False)
