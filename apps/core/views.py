from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render


def home(request):
    """Signed-in people land on their incidents; everyone else sees what Beacon is."""
    if request.user.is_authenticated:
        return redirect('incidents:list')
    return render(request, 'core/home.html')


def health(request):
    """Liveness/readiness probe for load balancers and uptime checks; fails if the database is unreachable."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return JsonResponse({'status': 'ok'})
