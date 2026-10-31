from django.contrib import admin

from .models import ActionItem, Postmortem, PostmortemEvent, Screenshot


class PostmortemEventInline(admin.TabularInline):
    model = PostmortemEvent
    extra = 0


class ActionItemInline(admin.TabularInline):
    model = ActionItem
    extra = 0


class ScreenshotInline(admin.TabularInline):
    model = Screenshot
    extra = 0
    readonly_fields = ['image']


@admin.register(Postmortem)
class PostmortemAdmin(admin.ModelAdmin):
    list_display = ['title', 'incident', 'status', 'created_at']
    list_filter = ['status']
    inlines = [PostmortemEventInline, ActionItemInline, ScreenshotInline]
