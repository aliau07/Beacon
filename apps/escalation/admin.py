from django.contrib import admin

from .models import EscalationLevel, EscalationPolicy, EscalationState


class EscalationLevelInline(admin.TabularInline):
    model = EscalationLevel
    extra = 0


@admin.register(EscalationPolicy)
class EscalationPolicyAdmin(admin.ModelAdmin):
    list_display = ['name', 'team', 'repeat_count']
    list_filter = ['team']
    inlines = [EscalationLevelInline]


@admin.register(EscalationState)
class EscalationStateAdmin(admin.ModelAdmin):
    list_display = ['incident', 'policy', 'level_index', 'cycle', 'next_run_at']
    readonly_fields = ['started_at', 'updated_at']
