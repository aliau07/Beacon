import threading
from unittest import mock, skipUnless

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.core.tests.factories import add_member, make_incident, make_service, make_team, make_user, owner_of

from . import services, signals
from .models import Incident, TimelineEntry

Status = Incident.Status


class StateMachineTests(TestCase):
    def setUp(self):
        self.service = make_service()
        self.user = owner_of(self.service.team)
        self.incident, _ = services.trigger(self.service, 'API 5xx above 5%', 'critical', dedup_key='5xx')

    def test_triggered_to_acknowledged_to_resolved(self):
        services.acknowledge(self.incident, self.user, via='Beacon')
        self.assertEqual((self.incident.status, self.incident.acknowledged_by), (Status.ACKNOWLEDGED, self.user))
        self.assertIsNotNone(self.incident.acknowledged_at)

        services.resolve(self.incident, self.user, via='Beacon')
        self.incident.refresh_from_db()
        self.assertEqual((self.incident.status, self.incident.resolved_by), (Status.RESOLVED, self.user))

    def test_triggered_straight_to_resolved(self):
        services.resolve(self.incident)

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Status.RESOLVED)
        self.assertIsNone(self.incident.acknowledged_at)

    def test_resolved_incidents_cannot_move(self):
        services.resolve(self.incident)

        with self.assertRaisesMessage(services.IncidentError, "is resolved, so it can't be acknowledged"):
            services.acknowledge(self.incident)
        with self.assertRaises(services.IncidentError):
            services.resolve(self.incident)

    def test_acknowledged_incidents_cannot_be_acknowledged_again(self):
        services.acknowledge(self.incident)

        with self.assertRaises(services.IncidentError):
            services.acknowledge(self.incident)

    def test_rules_are_checked_against_the_database_not_a_stale_copy(self):
        stale = Incident.objects.get(pk=self.incident.pk)
        services.resolve(self.incident)

        with self.assertRaises(services.IncidentError):
            services.acknowledge(stale)
        self.assertEqual(Incident.objects.get(pk=self.incident.pk).status, Status.RESOLVED)

    def test_can_transition(self):
        self.assertTrue(services.can_transition(self.incident, Status.ACKNOWLEDGED))
        self.assertFalse(services.can_transition(self.incident, Status.TRIGGERED))
        services.acknowledge(self.incident)
        self.assertFalse(services.can_transition(self.incident, Status.ACKNOWLEDGED))
        self.assertTrue(services.can_transition(self.incident, Status.RESOLVED))

    def test_every_change_is_on_the_timeline(self):
        services.acknowledge(self.incident, self.user, via='Beacon')
        services.add_note(self.incident, self.user, 'Rolling back release 42.')
        services.resolve(self.incident, None, via='the events API')

        entries = list(self.incident.timeline.values_list('kind', 'message', 'actor'))
        self.assertEqual(entries, [
            ('triggered', 'Triggered via the events API: API 5xx above 5%', None),
            ('acknowledged', f'Acknowledged by {self.user.display_name}.', self.user.pk),
            ('note', 'Rolling back release 42.', self.user.pk),
            ('resolved', 'Resolved via the events API.', None),
        ])

    def test_signals_are_sent_only_after_commit(self):
        received = []

        def receiver(sender, incident, **kwargs):
            received.append(incident.status)

        signals.incident_acknowledged.connect(receiver)
        self.addCleanup(signals.incident_acknowledged.disconnect, receiver)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            services.acknowledge(self.incident)
            self.assertEqual(received, [])

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(received, [Status.ACKNOWLEDGED])

    def test_trigger_validation(self):
        with self.assertRaises(services.IncidentError):
            services.trigger(self.service, '  ', 'error')
        with self.assertRaises(services.IncidentError):
            services.trigger(self.service, 'Something', 'catastrophic')

    def test_note_validation(self):
        with self.assertRaises(services.IncidentError):
            services.add_note(self.incident, self.user, '   ')
        with self.assertRaises(services.IncidentError):
            services.add_note(self.incident, self.user, 'x' * 5001)


class DedupTests(TestCase):
    def setUp(self):
        self.service = make_service()

    def test_one_open_incident_per_service_and_dedup_key(self):
        first, created = services.trigger(self.service, 'Disk full', 'error', dedup_key='disk')
        second, created_again = services.trigger(self.service, 'Disk still full', 'critical', dedup_key='disk')

        self.assertEqual((created, created_again), (True, False))
        self.assertEqual(first, second)
        second.refresh_from_db()
        self.assertEqual((second.alert_count, second.severity), (2, 'error'))
        self.assertEqual(second.timeline.filter(kind=TimelineEntry.Kind.ALERT).count(), 1)

    def test_the_database_rejects_a_second_open_incident(self):
        make_incident(self.service, dedup_key='disk')

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_incident(self.service, dedup_key='disk', status=Status.ACKNOWLEDGED)

    def test_resolved_incidents_do_not_block_the_key(self):
        make_incident(self.service, dedup_key='disk', status=Status.RESOLVED)
        make_incident(self.service, dedup_key='disk', status=Status.RESOLVED)

        incident, created = services.trigger(self.service, 'Disk full again', 'error', dedup_key='disk')

        self.assertTrue(created)
        self.assertEqual(Incident.objects.filter(dedup_key='disk').count(), 3)

    def test_a_concurrent_duplicate_is_caught_by_the_constraint(self):
        """Simulate the race: our lookup runs before the other request's incident is visible, so we try to insert
        a second open incident; the partial unique index raises IntegrityError and the event joins the winner."""
        winner = make_incident(self.service, dedup_key='disk')
        real_find_open = services.find_open
        lookups = []

        def stale_first_lookup(*args, **kwargs):
            lookups.append(args)
            return None if len(lookups) == 1 else real_find_open(*args, **kwargs)

        with mock.patch.object(services, 'find_open', side_effect=stale_first_lookup):
            incident, created = services.trigger(self.service, 'Disk full', 'error', dedup_key='disk')

        self.assertEqual(len(lookups), 2)
        self.assertFalse(created)
        self.assertEqual(incident, winner)
        self.assertEqual(Incident.objects.filter(dedup_key='disk').count(), 1)
        winner.refresh_from_db()
        self.assertEqual(winner.alert_count, 2)


@skipUnless(connection.vendor == 'postgresql', 'needs real concurrent transactions (run with DATABASE_URL=postgres://...)')
class DedupRaceOnPostgresTests(TransactionTestCase):
    def test_two_simultaneous_triggers_open_one_incident(self):
        service = make_service()
        barrier = threading.Barrier(2, timeout=10)
        state = threading.local()
        real_find_open = services.find_open
        results, errors = [], []

        def find_open_then_wait(*args, **kwargs):
            found = real_find_open(*args, **kwargs)
            if not getattr(state, 'waited', False):
                state.waited = True
                barrier.wait()  # both requests have looked and found nothing before either inserts
            return found

        def worker():
            try:
                results.append(services.trigger(service, 'Disk full', 'critical', dedup_key='disk'))
            except Exception as error:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(error)
            finally:
                connection.close()

        with mock.patch.object(services, 'find_open', find_open_then_wait):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [])
        created_flags = []
        for _, created in results:
            created_flags.append(created)
        self.assertEqual(sorted(created_flags), [False, True])
        incident = Incident.objects.get(dedup_key='disk')
        self.assertEqual(incident.alert_count, 2)


class IncidentViewTests(TestCase):
    def setUp(self):
        self.team = make_team('Platform')
        self.responder = add_member(self.team, make_user('linus'))
        self.service = make_service(self.team, 'Checkout API')
        self.incident = make_incident(self.service, summary='Checkout failing', severity='critical')

    def test_list_shows_open_incidents_of_my_teams_only(self):
        make_incident(make_service(), summary='Somebody else’s problem')
        make_incident(self.service, summary='Old and resolved', status=Status.RESOLVED)
        self.client.force_login(self.responder)

        response = self.client.get(reverse('incidents:list'))
        resolved = self.client.get(reverse('incidents:list'), {'status': 'resolved'})

        self.assertContains(response, 'Checkout failing')
        self.assertNotContains(response, 'Somebody else')
        self.assertNotContains(response, 'Old and resolved')
        self.assertContains(resolved, 'Old and resolved')
        self.assertNotContains(resolved, 'Checkout failing')

    def test_filter_by_severity_and_team(self):
        make_incident(self.service, summary='Slow search', severity='warning')
        self.client.force_login(self.responder)

        response = self.client.get(reverse('incidents:list'), {'severity': 'warning', 'team': self.team.slug})

        self.assertContains(response, 'Slow search')
        self.assertNotContains(response, 'Checkout failing')

    def test_outsiders_get_404(self):
        self.client.force_login(make_user())

        self.assertEqual(self.client.get(self.incident.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse('incidents:acknowledge', args=[self.incident.pk])).status_code, 404)

    def test_responders_acknowledge_and_resolve(self):
        self.client.force_login(self.responder)

        detail = self.client.get(self.incident.get_absolute_url())
        self.client.post(reverse('incidents:acknowledge', args=[self.incident.pk]))
        self.client.post(reverse('incidents:resolve', args=[self.incident.pk]))

        self.assertContains(detail, 'Acknowledge')
        self.incident.refresh_from_db()
        self.assertEqual((self.incident.status, self.incident.resolved_by), (Status.RESOLVED, self.responder))
        self.assertContains(self.client.get(self.incident.get_absolute_url()), 'Write a postmortem')

    def test_invalid_moves_show_an_error(self):
        services.resolve(self.incident)
        self.client.force_login(self.responder)

        response = self.client.post(reverse('incidents:acknowledge', args=[self.incident.pk]), follow=True)

        self.assertContains(response, "can&#x27;t be acknowledged")
        self.assertEqual(Incident.objects.get(pk=self.incident.pk).status, Status.RESOLVED)

    def test_notes(self):
        self.client.force_login(self.responder)

        self.client.post(reverse('incidents:note_add', args=[self.incident.pk]), {'text': 'Looking at the DB.'})

        self.assertContains(self.client.get(self.incident.get_absolute_url()), 'Looking at the DB.')

    def test_trigger_from_the_web(self):
        self.client.force_login(self.responder)

        response = self.client.post(reverse('incidents:create', args=[self.team.slug]), {
            'service': self.service.pk, 'summary': 'Customers report blank pages', 'severity': 'error',
        })

        incident = Incident.objects.get(summary='Customers report blank pages')
        self.assertRedirects(response, incident.get_absolute_url())
        self.assertEqual((incident.source, incident.created_by), (Incident.Source.WEB, self.responder))
        self.assertIn(f'by {self.responder.display_name}', incident.timeline.get().message)
