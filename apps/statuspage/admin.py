from django.contrib import admin

from .models import Component, StatusPage


class ComponentInline(admin.StackedInline):
    model = Component
    extra = 0
    filter_horizontal = ['services']


@admin.register(StatusPage)
class StatusPageAdmin(admin.ModelAdmin):
    list_display = ['title', 'team', 'slug', 'is_public']
    inlines = [ComponentInline]
