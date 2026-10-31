from django.urls import path

from . import views

app_name = 'statuspage'

urlpatterns = [
    path('teams/<slug:team_slug>/status-page/', views.manage, name='manage'),
    path('teams/<slug:team_slug>/status-page/components/', views.component_add, name='component_add'),
    path('status-components/<int:pk>/edit/', views.component_edit, name='component_edit'),
    path('status-components/<int:pk>/delete/', views.component_delete, name='component_delete'),
    path('status/<slug:slug>/', views.public, name='public'),
    path('status/<slug:slug>/summary.json', views.public_summary, name='public_summary'),
]
