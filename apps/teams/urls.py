from django.urls import path

from . import views

app_name = 'teams'

urlpatterns = [
    path('teams/', views.team_list, name='list'),
    path('teams/new/', views.team_create, name='create'),
    path('teams/<slug:slug>/', views.team_detail, name='detail'),
    path('teams/<slug:slug>/members/', views.member_add, name='member_add'),
    path('teams/<slug:slug>/members/<int:membership_id>/role/', views.member_role, name='member_role'),
    path('teams/<slug:slug>/members/<int:membership_id>/remove/', views.member_remove, name='member_remove'),
]
