import json
from datetime import UTC, datetime, timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.core.tests.factories import make_api_key, make_service, make_team, owner_of
from apps.incidents.models import Incident
from apps.services.services import revoke_api_key

from . import services
from .models import Alert, RateLimitWindow

URL = reverse('alerts:events')
TRIGGER = {'event_action': 'trigger', 'dedup_key': 'disk-db1', 'summary': 'Disk 95% full on db1', 'severity': 'critical'}


class EventsApiMixin:
    def setUp(self):
        self.service = make_service(name='Database')
        self.api_key, self.raw_key = make_api_key(self.service)

    def post(self, payload=None, key=None, raw_body=None, scheme='Bearer', client=None, **extra):
        body = raw_body if raw_body is not None else json.dumps(TRIGGER if payload is None else payload)
        headers = {'authorization': f'{scheme} {key or self.raw_key}'}
        return (client or self.client).post(URL, body, content_type='application/json', headers=headers, **extra)


class AuthenticationTests(EventsApiMixin, TestCase):
    def test_missing_header_is_401_with_a_json_error(self):
        response = self.client.post(URL, json.dumps(TRIGGER), content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('Bearer', response['WWW-Authenticate'])
        self.assertIn('API key', response.json()['error'])
        self.assertFalse(Incident.objects.exists())

    def test_unknown_scheme_and_unknown_key_are_401(self):
        self.assertEqual(self.post(scheme='Basic').status_code, 401)
        self.assertEqual(self.post(key='bcn_00000000_' + 'x' * 43).status_code, 401)
        self.assertEqual(self.post(key=self.api_key.key_hash).status_code, 401)

    def test_revoked_keys_are_401(self):
        revoke_api_key(self.api_key, owner_of(self.service.team))

        self.assertEqual(self.post().status_code, 401)

    def test_bearer_and_token_schemes_are_accepted(self):
        self.assertEqual(self.post(scheme='Bearer').status_code, 202)
        self.assertEqual(self.post(scheme='Token').status_code, 202)
        self.assertEqual(self.post(scheme='Token token=' + self.raw_key, key=' ').status_code, 202)

    def test_only_post_is_allowed(self):
        response = self.client.get(URL, headers={'authorization': f'Bearer {self.raw_key}'})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'POST')

    def test_no_csrf_token_is_needed(self):
        self.assertEqual(self.post(client=Client(enforce_csrf_checks=True)).status_code, 202)


class ValidationTests(EventsApiMixin, TestCase):
    def assertInvalid(self, response, *fields):
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body['error'], 'Invalid event.')
        self.assertEqual(sorted(body['errors']), sorted(fields))
        return body

    def test_body_must_be_json(self):
        response = self.post(raw_body='{"event_action": ')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Request body must be valid JSON.')

    def test_body_must_be_an_object(self):
        self.assertInvalid(self.post(payload=['trigger']), 'body')

    def test_event_action_is_checked(self):
        body = self.assertInvalid(self.post(payload={**TRIGGER, 'event_action': 'explode'}), 'event_action')
        self.assertIn('trigger, acknowledge, resolve', body['errors']['event_action'])
        self.assertInvalid(self.post(payload={'summary': 'x', 'severity': 'info'}), 'event_action')

    def test_trigger_needs_a_summary_and_a_known_severity(self):
        self.assertInvalid(self.post(payload={'event_action': 'trigger'}), 'summary', 'severity')
        body = self.assertInvalid(self.post(payload={**TRIGGER, 'severity': 'apocalyptic'}), 'severity')
        self.assertIn('critical, error, warning, info', body['errors']['severity'])
        self.assertInvalid(self.post(payload={**TRIGGER, 'summary': '   '}), 'summary')

    def test_acknowledge_and_resolve_need_a_dedup_key(self):
        self.assertInvalid(self.post(payload={'event_action': 'acknowledge'}), 'dedup_key')
        self.assertInvalid(self.post(payload={'event_action': 'resolve', 'dedup_key': ''}), 'dedup_key')

    def test_field_types_and_lengths(self):
        self.assertInvalid(self.post(payload={**TRIGGER, 'dedup_key': 42}), 'dedup_key')
        self.assertInvalid(self.post(payload={**TRIGGER, 'dedup_key': 'k' * 256}), 'dedup_key')
        self.assertInvalid(self.post(payload={**TRIGGER, 'summary': 's' * 256}), 'summary')
        self.assertInvalid(self.post(payload={**TRIGGER, 'details': 'not an object'}), 'details')
        self.assertFalse(Incident.objects.exists())

    @override_settings(EVENTS_MAX_BODY_BYTES=1024)
    def test_oversized_bodies_are_413(self):
        response = self.post(payload={**TRIGGER, 'details': {'log': 'x' * 2000}})

        self.assertEqual(response.status_code, 413)


class EventProcessingTests(EventsApiMixin, TestCase):
    def test_trigger_opens_an_incident_and_logs_the_alert(self):
        response = self.post(payload={**TRIGGER, 'details': {'host': 'db1'}})

        self.assertEqual(response.status_code, 202)
        body = response.json()
        incident = Incident.objects.get()
        self.assertEqual(body, {
            'status': 'success', 'outcome': 'triggered', 'message': 'Incident triggered.', 'dedup_key': 'disk-db1',
            'incident_id': incident.pk, 'incident_status': 'triggered',
        })
        self.assertEqual((incident.service, incident.severity, incident.details), (self.service, 'critical', {'host': 'db1'}))
        alert = Alert.objects.get()
        self.assertEqual((alert.incident, alert.outcome, alert.api_key), (incident, 'triggered', self.api_key))

    def test_trigger_without_dedup_key_gets_one(self):
        body = self.post(payload={'event_action': 'trigger', 'summary': 'CPU hot', 'severity': 'warning'}).json()

        self.assertRegex(body['dedup_key'], r'^[0-9a-f]{32}$')
        self.assertEqual(Incident.objects.get().dedup_key, body['dedup_key'])

    def test_repeated_triggers_are_grouped(self):
        first = self.post().json()
        second = self.post(payload={**TRIGGER, 'summary': 'Disk 97% full on db1'}).json()

        self.assertEqual(second['outcome'], 'deduplicated')
        self.assertEqual(first['incident_id'], second['incident_id'])
        self.assertEqual(Incident.objects.get().alert_count, 2)

    def test_same_dedup_key_on_another_service_is_another_incident(self):
        _, other_key = make_api_key(make_service(self.service.team, 'Cache'))

        self.post()
        self.post(key=other_key)

        self.assertEqual(Incident.objects.count(), 2)

    def test_acknowledge_then_resolve(self):
        self.post()

        acknowledged = self.post(payload={'event_action': 'acknowledge', 'dedup_key': 'disk-db1'})
        resolved = self.post(payload={'event_action': 'resolve', 'dedup_key': 'disk-db1'})

        self.assertEqual((acknowledged.status_code, acknowledged.json()['outcome']), (202, 'acknowledged'))
        self.assertEqual((resolved.status_code, resolved.json()['incident_status']), (202, 'resolved'))
        incident = Incident.objects.get()
        self.assertEqual(incident.status, 'resolved')
        self.assertIsNone(incident.resolved_by)
        self.assertEqual(list(incident.timeline.values_list('kind', flat=True)), ['triggered', 'acknowledged', 'resolved'])

    def test_events_the_state_machine_rejects_are_accepted_but_ignored(self):
        self.post()
        self.post(payload={'event_action': 'acknowledge', 'dedup_key': 'disk-db1'})

        again = self.post(payload={'event_action': 'acknowledge', 'dedup_key': 'disk-db1'}).json()
        unknown = self.post(payload={'event_action': 'resolve', 'dedup_key': 'never-seen'}).json()

        self.assertEqual(again['outcome'], 'ignored')
        self.assertIn("can't be acknowledged", again['message'])
        self.assertEqual((unknown['outcome'], unknown['incident_id']), ('ignored', None))
        self.assertEqual(Incident.objects.get().status, 'acknowledged')

    def test_trigger_after_resolve_opens_a_new_incident(self):
        self.post()
        self.post(payload={'event_action': 'resolve', 'dedup_key': 'disk-db1'})

        body = self.post().json()

        self.assertEqual(body['outcome'], 'triggered')
        self.assertEqual(Incident.objects.count(), 2)

    def test_trigger_while_acknowledged_keeps_it_acknowledged(self):
        self.post()
        self.post(payload={'event_action': 'acknowledge', 'dedup_key': 'disk-db1'})

        body = self.post().json()

        self.assertEqual((body['outcome'], body['incident_status']), ('deduplicated', 'acknowledged'))


START = datetime(2026, 3, 2, 12, 0, 10, tzinfo=UTC)


@override_settings(EVENTS_RATE_LIMIT=2, EVENTS_RATE_LIMIT_WINDOW=60)
class RateLimitTests(EventsApiMixin, TestCase):
    def at(self, moment):
        return mock.patch('django.utils.timezone.now', return_value=moment)

    def test_over_the_limit_is_429_with_retry_after(self):
        with self.at(START):
            first, second, third = self.post(), self.post(), self.post()

        self.assertEqual([first.status_code, second.status_code, third.status_code], [202, 202, 429])
        self.assertEqual(third['Retry-After'], '50')
        self.assertEqual(third['X-RateLimit-Remaining'], '0')
        self.assertIn('Rate limit exceeded: 2 requests per 60 seconds', third.json()['error'])
        self.assertEqual(Incident.objects.get().alert_count, 2)

    def test_limit_headers_on_success(self):
        with self.at(START):
            response = self.post()

        self.assertEqual((response['X-RateLimit-Limit'], response['X-RateLimit-Remaining']), ('2', '1'))

    def test_the_count_resets_in_the_next_fixed_window(self):
        with self.at(START):
            self.post(), self.post()
        with self.at(START + timedelta(seconds=49)):
            self.assertEqual(self.post().status_code, 429)
        with self.at(START + timedelta(seconds=50)):
            self.assertEqual(self.post().status_code, 202)
        self.assertEqual(RateLimitWindow.objects.count(), 1)  # old windows are cleaned up

    def test_each_key_has_its_own_limit(self):
        _, other_key = make_api_key(self.service, 'Second')
        with self.at(START):
            self.post(), self.post()
            self.assertEqual(self.post().status_code, 429)
            self.assertEqual(self.post(key=other_key).status_code, 202)

    def test_invalid_requests_count_too(self):
        with self.at(START):
            self.post(raw_body='nope'), self.post(raw_body='nope')
            self.assertEqual(self.post().status_code, 429)

    def test_window_arithmetic(self):
        end_of_window = datetime(2026, 3, 2, 12, 0, 59, tzinfo=UTC)

        result = services.check_rate_limit(self.api_key, end_of_window)

        self.assertEqual(result, services.RateLimit(True, 2, 1, 1))
        window = RateLimitWindow.objects.get()
        self.assertEqual(window.window_start, datetime(2026, 3, 2, 12, 0, tzinfo=UTC))


@override_settings(EVENTS_RATE_LIMIT=1000)
class ProcessEventTests(TestCase):
    def test_process_event_reports_every_problem_at_once(self):
        api_key, _ = make_api_key()

        with self.assertRaises(services.EventError) as caught:
            services.process_event(api_key, {'event_action': 'trigger', 'dedup_key': 7, 'details': []})

        self.assertEqual(sorted(caught.exception.errors), ['dedup_key', 'details', 'severity', 'summary'])

    def test_team_outsiders_never_see_api_events_on_their_dashboard(self):
        api_key, raw_key = make_api_key()
        other_team = make_team()
        self.client.post(URL, json.dumps(TRIGGER), content_type='application/json',
                         headers={'authorization': f'Bearer {raw_key}'})
        self.client.force_login(owner_of(other_team))

        response = self.client.get(reverse('incidents:list'))

        self.assertNotContains(response, TRIGGER['summary'])
