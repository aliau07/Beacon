from django.contrib import admin

from .models import Override, Rotation, RotationParticipant, Schedule


class RotationParticipantInline(admin.TabularInline):
    model = RotationParticipant
    extra = 0


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ['name', 'team', 'created_at']
    list_filter = ['team']
    search_fields = ['name']


@admin.register(Rotation)
class RotationAdmin(admin.ModelAdmin):
    list_display = ['name', 'schedule', 'time_zone', 'start_date', 'handoff_time', 'shift_length_days', 'priority']
    list_filter = ['schedule__team']
    inlines = [RotationParticipantInline]


@admin.register(Override)
class OverrideAdmin(admin.ModelAdmin):
    list_display = ['schedule', 'user', 'starts_at', 'ends_at', 'reason']
    list_filter = ['schedule__team']
