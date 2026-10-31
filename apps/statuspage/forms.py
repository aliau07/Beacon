from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import Component, StatusPage


class StatusPageForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StatusPage
        fields = ['title', 'slug', 'description', 'is_public']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def validate_unique(self):
        """Slug clashes are checked by the service layer."""


class ComponentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Component
        fields = ['name', 'description', 'position', 'services', 'override_status', 'override_message']
        widgets = {'services': forms.CheckboxSelectMultiple}

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['services'].queryset = team.services.all()
        self.fields['override_status'].label = 'Manual status'
