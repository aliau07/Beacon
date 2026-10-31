from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import Service


class ServiceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ['name', 'description', 'escalation_policy']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['escalation_policy'].queryset = team.escalation_policies.all()
        self.fields['escalation_policy'].help_text = 'Who gets paged for this service. Without one, nobody is.'

    def validate_unique(self):
        """Name clashes are checked by the service layer (the form has no team field)."""


class ApiKeyForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(max_length=100, label='Key name', help_text='Where it will be used, e.g. "Alertmanager".')
