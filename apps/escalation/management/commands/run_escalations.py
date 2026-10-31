import time

from django.core.management.base import BaseCommand

from apps.escalation.services import run_due


class Command(BaseCommand):
    help = (
        'Page the next escalation level for every unacknowledged incident whose current level has timed out. '
        'Run it every minute from cron, or pass --interval to keep it running (handy in development).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=0, help='Keep running, checking every this many seconds.')

    def handle(self, *args, **options):
        while True:
            escalated = run_due()
            self.stdout.write(f'{escalated} incident(s) escalated.')
            if options['interval'] <= 0:
                break
            time.sleep(options['interval'])
