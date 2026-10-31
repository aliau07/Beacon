from django.urls import path

from . import views

app_name = 'services'

urlpatterns = [
    path('teams/<slug:team_slug>/services/', views.service_list, name='list'),
    path('teams/<slug:team_slug>/services/new/', views.service_create, name='create'),
    path('services/<int:pk>/', views.service_detail, name='detail'),
    path('services/<int:pk>/edit/', views.service_edit, name='edit'),
    path('services/<int:pk>/api-keys/', views.api_key_create, name='api_key_create'),
    path('api-keys/<int:pk>/revoke/', views.api_key_revoke, name='api_key_revoke'),
]
