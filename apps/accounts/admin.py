from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class BeaconUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'time_zone', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (('Beacon', {'fields': ['time_zone', 'avatar']}),)
