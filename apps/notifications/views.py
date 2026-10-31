from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .models import Notification


@login_required
def inbox(request):
    page = Paginator(services.inbox_for(request.user), 30).get_page(request.GET.get('page'))
    return render(request, 'notifications/inbox.html', {'page_obj': page, 'notifications': page.object_list})


@login_required
@require_POST
def open_notification(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    services.mark_read(notification)
    if notification.incident_id:
        return redirect(notification.incident)
    return redirect('notifications:inbox')


@login_required
@require_POST
def mark_all_read(request):
    count = services.mark_all_read(request.user)
    messages.success(request, f'{count} notification{"s" if count != 1 else ""} marked as read.')
    return redirect('notifications:inbox')
