from django.urls import path

from . import views

app_name = 'incidents'

urlpatterns = [
    path('incidents/', views.incident_list, name='list'),
    path('teams/<slug:team_slug>/incidents/new/', views.incident_create, name='create'),
    path('incidents/<int:pk>/', views.incident_detail, name='detail'),
    path('incidents/<int:pk>/acknowledge/', views.incident_action, {'action': 'acknowledge'}, name='acknowledge'),
    path('incidents/<int:pk>/resolve/', views.incident_action, {'action': 'resolve'}, name='resolve'),
    path('incidents/<int:pk>/notes/', views.note_add, name='note_add'),
]
