from django.contrib import admin

from .models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['received_at', 'service', 'action', 'outcome', 'dedup_key', 'incident']
    list_filter = ['action', 'outcome', 'service__team']
    search_fields = ['dedup_key', 'summary']
    readonly_fields = [field.name for field in Alert._meta.fields]
