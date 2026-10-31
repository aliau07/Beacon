from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import Membership


class TeamForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(max_length=100)


class AddMemberForm(BootstrapFormMixin, forms.Form):
    identifier = forms.CharField(label='Username or email', max_length=254)
    role = forms.ChoiceField(choices=Membership.Role.choices, initial=Membership.Role.RESPONDER)


class RoleForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(choices=Membership.Role.choices)
