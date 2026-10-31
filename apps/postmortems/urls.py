from django.urls import path

from . import views

app_name = 'postmortems'

urlpatterns = [
    path('incidents/<int:incident_id>/postmortem/', views.start, name='start'),
    path('postmortems/<int:pk>/', views.detail, name='detail'),
    path('postmortems/<int:pk>/edit/', views.edit, name='edit'),
    path('postmortems/<int:pk>/publish/', views.publish, name='publish'),
    path('postmortems/<int:pk>/timeline/', views.event_add, name='event_add'),
    path('postmortems/<int:pk>/action-items/', views.action_add, name='action_add'),
    path('action-items/<int:pk>/toggle/', views.action_toggle, name='action_toggle'),
    path('postmortems/<int:pk>/screenshots/', views.screenshot_add, name='screenshot_add'),
    path('screenshots/<int:pk>/delete/', views.screenshot_delete, name='screenshot_delete'),
]
