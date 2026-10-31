from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView

from apps.core.images import ImageError

from . import services
from .forms import LoginForm, ProfileForm, SignupForm, StyledPasswordChangeForm


class SignupView(CreateView):
    form_class = SignupForm
    template_name = 'accounts/signup.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('core:home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, f'Welcome, {user.username}! Create a team or ask a teammate to add you to theirs.')
        return redirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return next_url
        return reverse('teams:list')


class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                if form.cleaned_data['new_avatar']:
                    services.set_avatar(user, form.cleaned_data['new_avatar'])
                elif form.cleaned_data['remove_avatar']:
                    services.remove_avatar(user)
        except ImageError as error:
            form.add_error('new_avatar', str(error))
        else:
            messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('accounts:profile')
    success_message = 'Your password has been changed.'
