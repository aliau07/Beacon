from django.urls import path

from . import views

app_name = 'escalation'

urlpatterns = [
    path('teams/<slug:team_slug>/escalation-policies/', views.policy_list, name='policy_list'),
    path('teams/<slug:team_slug>/escalation-policies/new/', views.policy_create, name='policy_create'),
    path('escalation-policies/<int:pk>/', views.policy_detail, name='policy_detail'),
    path('escalation-policies/<int:policy_id>/levels/', views.level_add, name='level_add'),
    path('escalation-levels/<int:pk>/delete/', views.level_delete, name='level_delete'),
]
