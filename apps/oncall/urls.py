from django.urls import path

from . import views

app_name = 'oncall'

urlpatterns = [
    path('oncall/', views.now, name='now'),
    path('teams/<slug:team_slug>/schedules/', views.schedule_list, name='schedule_list'),
    path('teams/<slug:team_slug>/schedules/new/', views.schedule_create, name='schedule_create'),
    path('schedules/<int:pk>/', views.schedule_detail, name='schedule_detail'),
    path('schedules/<int:schedule_id>/rotations/new/', views.rotation_form, name='rotation_create'),
    path('rotations/<int:pk>/edit/', views.rotation_form, name='rotation_edit'),
    path('rotations/<int:pk>/delete/', views.rotation_delete, name='rotation_delete'),
    path('schedules/<int:schedule_id>/overrides/', views.override_create, name='override_create'),
    path('overrides/<int:pk>/delete/', views.override_delete, name='override_delete'),
]
