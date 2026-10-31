from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('inbox/', views.inbox, name='inbox'),
    path('inbox/<int:pk>/open/', views.open_notification, name='open'),
    path('inbox/read-all/', views.mark_all_read, name='mark_all_read'),
]
