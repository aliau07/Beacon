from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Beacon admin'
admin.site.site_title = 'Beacon admin'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls', namespace='core')),
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),
    path('api/v1/', include('apps.alerts.urls', namespace='alerts')),
    path('', include('apps.teams.urls', namespace='teams')),
    path('', include('apps.services.urls', namespace='services')),
    path('', include('apps.incidents.urls', namespace='incidents')),
    path('', include('apps.oncall.urls', namespace='oncall')),
    path('', include('apps.escalation.urls', namespace='escalation')),
    path('', include('apps.notifications.urls', namespace='notifications')),
    path('', include('apps.statuspage.urls', namespace='statuspage')),
    path('', include('apps.postmortems.urls', namespace='postmortems')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
