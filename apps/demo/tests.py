import json
import os
import re
from io import StringIO
from unittest import mock

from django.contrib.auth import authenticate
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.incidents.models import Incident
from apps.notifications.models import Notification
from apps.postmortems.models import Postmortem
from apps.services.models import ApiKey
from apps.statuspage.models import StatusPage
from apps.teams.models import Team


class SeedDemoDataTests(TestCase):
    def seed(self, *args):
        out = StringIO()
        with mock.patch.dict(os.environ, {'DEMO_PASSWORD': 'demo-pass-123'}), self.captureOnCommitCallbacks(execute=True):
            call_command('seed_demo_data', *args, stdout=out)
        return out.getvalue()

    def test_seed_creates_a_working_demo(self):
        output = self.seed()

        team = Team.objects.get(name='Demo Ops')
        self.assertEqual(team.memberships.count(), 4)
        self.assertEqual(team.services.count(), 3)
        self.assertEqual(team.schedules.count(), 2)
        statuses = sorted(Incident.objects.values_list('status', flat=True))
        self.assertEqual(statuses, ['acknowledged', 'resolved', 'triggered'])
        self.assertTrue(Postmortem.objects.exists())
        self.assertTrue(StatusPage.objects.filter(slug='demo-ops', is_public=True).exists())
        self.assertTrue(Notification.objects.filter(kind='page').exists())
        self.assertIsNotNone(authenticate(username='ada', password='demo-pass-123'))
        self.assertIn('demo-pass-123', output)
        self.assertEqual(len(re.findall(r'bcn_[0-9a-f]{8}_\S+', output)), 4)  # three services plus the curl example

    def test_a_printed_api_key_works(self):
        output = self.seed()
        raw_key = re.search(r'Checkout API\s+(bcn_\S+)', output).group(1)

        response = self.client.post(reverse('alerts:events'), json.dumps({
            'event_action': 'trigger', 'dedup_key': 'demo-1', 'summary': 'Demo alert', 'severity': 'error',
        }), content_type='application/json', headers={'authorization': f'Bearer {raw_key}'})

        self.assertEqual(response.status_code, 202)

    def test_rerunning_rotates_keys_and_reset_rebuilds(self):
        first = self.seed()
        old_key = re.search(r'Search\s+(bcn_\S+)', first).group(1)

        second = self.seed()
        self.assertIn('already exists', second)
        self.assertEqual(Team.objects.filter(name='Demo Ops').count(), 1)
        self.assertEqual(ApiKey.objects.filter(revoked_at__isnull=True).count(), 3)
        self.assertNotIn(old_key, second)

        self.seed('--reset')
        self.assertEqual(Incident.objects.count(), 3)
        self.assertEqual(ApiKey.objects.count(), 3)
