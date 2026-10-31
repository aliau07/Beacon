from django.contrib import admin

from .models import Incident, TimelineEntry


class TimelineEntryInline(admin.TabularInline):
    model = TimelineEntry
    extra = 0
    fields = ['created_at', 'kind', 'message', 'actor']
    readonly_fields = fields
    can_delete = False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'service', 'team', 'severity', 'status', 'alert_count', 'created_at']
    list_filter = ['status', 'severity', 'team']
    search_fields = ['summary', 'dedup_key']
    list_select_related = ['service', 'team']
    readonly_fields = ['status', 'acknowledged_at', 'acknowledged_by', 'resolved_at', 'resolved_by', 'created_at',
                       'updated_at']
    inlines = [TimelineEntryInline]
