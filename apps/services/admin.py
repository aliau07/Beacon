from django.contrib import admin

from .models import ApiKey, Service


class ApiKeyInline(admin.TabularInline):
    model = ApiKey
    extra = 0
    fields = ['name', 'prefix', 'created_at', 'last_used_at', 'revoked_at']
    readonly_fields = ['name', 'prefix', 'created_at', 'last_used_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # keys are created in the app, where the secret is shown once


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'team', 'escalation_policy', 'created_at']
    list_filter = ['team']
    search_fields = ['name']
    inlines = [ApiKeyInline]
