import os
import secrets
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.escalation import services as escalation
from apps.incidents import services as incidents
from apps.oncall import services as oncall
from apps.postmortems import services as postmortems
from apps.services import services as service_rules
from apps.services.models import ApiKey
from apps.statuspage import services as statuspage
from apps.teams import services as teams
from apps.teams.models import Membership, Team

TEAM_NAME = 'Demo Ops'
DEMO_KEY_NAME = 'Demo key'
Role = Membership.Role

DEMO_USERS = [
    # username, role (None = not on the team), first, last, time zone, description
    ('admin', None, 'Site', 'Admin', 'UTC', 'superuser: Django admin'),
    ('ada', Role.OWNER, 'Ada', 'Lovelace', 'Europe/Dublin', 'team owner, last escalation level'),
    ('grace', Role.ADMIN, 'Grace', 'Hopper', 'America/New_York', 'team admin, primary rotation'),
    ('linus', Role.RESPONDER, 'Linus', 'Torvalds', 'Europe/Helsinki', 'responder, primary and secondary rotations'),
    ('margaret', Role.RESPONDER, 'Margaret', 'Hamilton', 'America/Los_Angeles', 'responder, secondary rotation'),
]

SERVICES = [
    ('Checkout API', 'Takes payments and creates orders.'),
    ('Payments worker', 'Settles card payments with the acquirer.'),
    ('Search', 'Product search and autocomplete.'),
]


class Command(BaseCommand):
    help = (
        'Create a demo team with users, services (each with a fresh API key), on-call schedules, an escalation '
        'policy, incidents in every state, a postmortem and a public status page. Passwords are generated on every '
        'run (or taken from DEMO_PASSWORD) and printed with the API keys; neither is stored in plain text.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help=f'Delete the "{TEAM_NAME}" team and everything in it first.')

    def handle(self, *args, **options):
        with transaction.atomic():
            if options['reset']:
                Team.objects.filter(name=TEAM_NAME).delete()
                self.stdout.write(f'Removed the "{TEAM_NAME}" team and its data.')
            credentials, users = self.create_users()
            team = Team.objects.filter(name=TEAM_NAME).first()
            if team is None:
                team = self.create_team(users)
                created = True
            else:
                self.stdout.write(f'The "{TEAM_NAME}" team already exists, so only passwords and API keys were renewed '
                                  '(use --reset to rebuild it).')
                created = False
            keys = self.rotate_api_keys(team, users['ada'])
        # Paging emails for the demo incidents are sent once the transaction above commits.
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created "{TEAM_NAME}" with services, schedules, an escalation '
                                                 'policy, incidents, a postmortem and a status page.'))
        self.print_summary(team, credentials, keys)

    def create_users(self):
        User = get_user_model()
        shared_password = os.environ.get('DEMO_PASSWORD')
        credentials, users = [], {}
        for username, role, first, last, time_zone, description in DEMO_USERS:
            password = shared_password or secrets.token_urlsafe(12)
            user, _ = User.objects.get_or_create(username=username, defaults={'email': f'{username}@example.com'})
            user.first_name, user.last_name, user.time_zone = first, last, time_zone
            user.is_staff = user.is_superuser = role is None
            user.set_password(password)
            user.save()
            credentials.append((username, password, description))
            users[username] = user
        return credentials, users

    def create_team(self, users):
        ada = users['ada']
        team = teams.create_team(TEAM_NAME, ada)
        for username, role, *_ in DEMO_USERS:
            if role not in (None, Role.OWNER):
                teams.add_member(team, ada, users[username], role)

        today = timezone.localdate()
        last_monday = today - timedelta(days=today.weekday())
        primary = oncall.create_schedule(team, ada, 'Primary on-call', 'Weekly, handing off Mondays 09:00 Dublin time.')
        oncall.save_rotation(primary, ada, [users['grace'], users['linus'], users['ada']], name='Weekly',
                             time_zone='Europe/Dublin', start_date=last_monday, handoff_time=time(9, 0),
                             shift_length_days=7, priority=1)
        secondary = oncall.create_schedule(team, ada, 'Secondary on-call', 'Daily, handing off at 17:00 New York time.')
        oncall.save_rotation(secondary, ada, [users['margaret'], users['linus']], name='Daily',
                             time_zone='America/New_York', start_date=last_monday, handoff_time=time(17, 0),
                             shift_length_days=1, priority=1)
        tomorrow_noon = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        oncall.create_override(primary, ada, users['margaret'], tomorrow_noon, tomorrow_noon + timedelta(hours=6),
                               'Covering while Grace is at the dentist')

        policy = escalation.create_policy(team, ada, 'Default', 'Primary, then secondary, then the team owner.', repeat_count=1)
        escalation.add_level(policy, ada, 5, target_schedule=primary)
        escalation.add_level(policy, ada, 10, target_schedule=secondary)
        escalation.add_level(policy, ada, 15, target_user=ada)

        services = {}
        for name, description in SERVICES:
            services[name] = service_rules.create_service(team, ada, name, description, escalation_policy=policy)

        incidents.trigger(services['Checkout API'], 'Checkout error rate above 5%', 'critical',
                          dedup_key='checkout-5xx', details={'error_rate': '7.2%', 'region': 'eu-west-1'})
        queue, _ = incidents.trigger(services['Payments worker'], 'Settlement queue depth growing', 'warning',
                                     dedup_key='settlement-queue', details={'depth': 18250})
        incidents.acknowledge(queue, users['grace'], via='Beacon')
        latency, _ = incidents.trigger(services['Search'], 'Search p99 latency above 2s', 'error', dedup_key='search-p99')
        incidents.add_note(latency, users['linus'], 'Index rebuild started at 02:00 is still running; pausing it.')
        incidents.resolve(latency, users['linus'], via='Beacon')

        postmortem = postmortems.start_postmortem(latency, users['linus'])
        postmortems.update_postmortem(
            postmortem, users['linus'], postmortem.title, postmortem.impact,
            'A nightly full index rebuild ran on the live cluster and saturated its disks.',
        )
        postmortems.add_action_item(postmortem, users['linus'], 'Run index rebuilds on a standby cluster and swap aliases',
                                    owner=users['linus'], due_date=today + timedelta(days=14))
        postmortems.add_action_item(postmortem, users['linus'], 'Alert on disk I/O wait before latency suffers',
                                    owner=users['margaret'])

        page = statuspage.save_page(team, ada, 'Demo Ops status', 'demo-ops', 'Live status of the Demo Ops shop.')
        statuspage.save_component(page, ada, 'Checkout', [services['Checkout API'], services['Payments worker']], position=1)
        statuspage.save_component(page, ada, 'Search', [services['Search']], position=2)
        statuspage.save_component(page, ada, 'Developer docs', [], position=3, override_status='maintenance',
                                  override_message='Moving to a new host; back by 18:00 UTC.')
        return team

    def rotate_api_keys(self, team, actor):
        """API keys can't be shown twice, so each run revokes the old demo keys and prints new ones."""
        ApiKey.objects.filter(service__team=team, name=DEMO_KEY_NAME, revoked_at__isnull=True).update(revoked_at=timezone.now())
        keys = []
        for service in team.services.all():
            _, raw_key = service_rules.create_api_key(service, actor, DEMO_KEY_NAME)
            keys.append((service.name, raw_key))
        return keys

    def print_summary(self, team, credentials, keys):
        site = settings.SITE_URL.rstrip('/')
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Demo accounts'))
        for username, password, description in credentials:
            self.stdout.write(f'  {username:<10} {password:<20} ({description})')
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('API keys (shown once; re-run to get new ones)'))
        for service_name, raw_key in keys:
            self.stdout.write(f'  {service_name:<16} {raw_key}')
        self.stdout.write('')
        self.stdout.write(f'Status page: {site}{reverse("statuspage:public", args=["demo-ops"])}')
        if keys:
            self.stdout.write('Try the events API:')
            self.stdout.write(f'  curl -X POST {site}{reverse("alerts:events")} -H "Authorization: Bearer {keys[0][1]}" \\')
            self.stdout.write('       -H "Content-Type: application/json" \\')
            self.stdout.write('       -d \'{"event_action": "trigger", "dedup_key": "demo-1", "summary": "Demo alert", "severity": "error"}\'')
        self.stdout.write('These passwords and keys are not stored anywhere in plain text; re-run this command to rotate them.')
