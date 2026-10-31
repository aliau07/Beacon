from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from apps.core.forms import BootstrapFormMixin
from apps.core.validators import time_zone_choices

User = get_user_model()


class UniqueEmailMixin:
    def clean_email(self):
        email = self.cleaned_data['email']
        others = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email


class SignupForm(BootstrapFormMixin, UniqueEmailMixin, UserCreationForm):
    """Registration with Django's password validators and a unique email address (pages are emailed to it)."""

    email = forms.EmailField()
    time_zone = forms.ChoiceField(choices=time_zone_choices, initial='UTC')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email', 'time_zone']


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass


class ProfileForm(BootstrapFormMixin, UniqueEmailMixin, forms.ModelForm):
    email = forms.EmailField()
    time_zone = forms.ChoiceField(choices=time_zone_choices)
    new_avatar = forms.ImageField(
        required=False, label='Avatar', help_text='JPEG, PNG, WebP or GIF. Cropped to a square; photo metadata is removed.',
    )
    remove_avatar = forms.BooleanField(required=False, label='Remove my avatar')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'time_zone']


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass
