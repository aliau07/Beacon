import threading
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from unittest import mock, skipUnless

from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.core.tests.factories import (
    add_member, make_incident, make_override, make_policy, make_rotation, make_schedule, make_service, make_team,
    make_user, owner_of,
)
from apps.incidents import services as incidents
from apps.notifications.models import Notification
from apps.teams.services import TeamPermissionDenied

from . import services
from .models import EscalationLevel, EscalationState

T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


def at(moment):
    return mock.patch('django.utils.timezone.now', return_value=moment)


def paged(incident):
    usernames = []
    for notification in Notification.objects.filter(incident=incident, kind='page').order_by('pk'):
        usernames.append(notification.recipient.username)
    return usernames


class EscalationTimingTests(TestCase):
    """Level 1 (linus, 5 min) then level 2 (whoever is on call for Primary, 10 min); timezone.now is mocked."""

    def setUp(self):
        self.team = make_team('Platform')
        self.linus = add_member(self.team, make_user('linus'))
        self.grace = add_member(self.team, make_user('grace'))
        self.margaret = add_member(self.team, make_user('margaret'))
        self.primary = make_schedule(self.team, 'Primary')
        make_rotation(self.primary, [self.grace], start_date=date(2026, 1, 5))
        self.policy = make_policy(self.team, [self.linus, self.primary], name='Default')
        EscalationLevel.objects.filter(policy=self.policy, position=1).update(delay_minutes=10)
        self.service = make_service(self.team, 'Checkout API', self.policy)

    def trigger(self, moment=T0, summary='Checkout failing'):
        with at(moment), self.captureOnCommitCallbacks(execute=True):
            incident, _ = incidents.trigger(self.service, summary, 'critical')
        return incident

    def run_at(self, moment):
        with at(moment), self.captureOnCommitCallbacks(execute=True):
            return services.run_due()

    def test_trigger_pages_level_one_by_email_and_inbox(self):
        incident = self.trigger()

        self.assertEqual(paged(incident), ['linus'])
        self.assertEqual(mail.outbox[0].to, ['linus@example.com'])
        self.assertIn('Default, level 1', mail.outbox[0].body)
        state = EscalationState.objects.get(incident=incident)
        self.assertEqual((state.level_index, state.next_run_at), (0, T0 + timedelta(minutes=5)))
        self.assertTrue(incident.timeline.filter(kind='paged', message__startswith='Paged linus').exists())

    def test_nothing_happens_before_the_delay(self):
        incident = self.trigger()

        self.assertEqual(self.run_at(T0 + timedelta(minutes=4, seconds=59)), 0)
        self.assertEqual(paged(incident), ['linus'])

    def test_the_next_level_is_paged_when_the_delay_passes(self):
        incident = self.trigger()

        self.assertEqual(self.run_at(T0 + timedelta(minutes=5)), 1)

        self.assertEqual(paged(incident), ['linus', 'grace'])
        state = EscalationState.objects.get(incident=incident)
        self.assertEqual((state.level_index, state.next_run_at), (1, T0 + timedelta(minutes=15)))
        self.assertTrue(incident.timeline.filter(kind='escalated', message__contains='level 2').exists())
        self.assertTrue(incident.timeline.filter(message='Paged grace (level 2 via Primary).').exists())

    def test_schedule_levels_page_whoever_is_on_call_then_including_overrides(self):
        make_override(self.primary, self.margaret, T0, T0 + timedelta(hours=1))
        incident = self.trigger()

        self.run_at(T0 + timedelta(minutes=5))

        self.assertEqual(paged(incident), ['linus', 'margaret'])

    def test_acknowledging_stops_the_escalation(self):
        incident = self.trigger()
        with at(T0 + timedelta(minutes=2)), self.captureOnCommitCallbacks(execute=True):
            incidents.acknowledge(incident, self.linus, via='Beacon')

        self.assertEqual(self.run_at(T0 + timedelta(minutes=30)), 0)
        self.assertEqual(paged(incident), ['linus'])
        self.assertIsNone(EscalationState.objects.get(incident=incident).next_run_at)

    def test_resolving_stops_the_escalation(self):
        incident = self.trigger()
        with self.captureOnCommitCallbacks(execute=True):
            incidents.resolve(incident)

        self.assertEqual(self.run_at(T0 + timedelta(hours=1)), 0)
        self.assertEqual(paged(incident), ['linus'])

    def test_an_acknowledgement_that_races_the_runner_still_wins(self):
        """The receiver that clears next_run_at hasn't run yet, but the runner re-reads the incident under lock."""
        incident = self.trigger()
        incidents.acknowledge(incident)  # no captureOnCommitCallbacks: the stop receiver never runs

        self.assertEqual(self.run_at(T0 + timedelta(minutes=10)), 0)
        self.assertEqual(paged(incident), ['linus'])

    def test_the_policy_repeats_then_stops(self):
        self.policy.repeat_count = 1
        self.policy.save()
        incident = self.trigger()

        moments = [T0 + timedelta(minutes=5), T0 + timedelta(minutes=15), T0 + timedelta(minutes=20),
                   T0 + timedelta(minutes=30)]
        results = []
        for moment in moments:
            results.append(self.run_at(moment))

        self.assertEqual(results, [1, 1, 1, 0])
        self.assertEqual(paged(incident), ['linus', 'grace', 'linus', 'grace'])
        self.assertTrue(incident.timeline.filter(message__contains='level 1, repeat 1').exists())
        self.assertTrue(incident.timeline.filter(message__startswith='Escalation finished').exists())
        self.assertIsNone(EscalationState.objects.get(incident=incident).next_run_at)
        self.assertEqual(self.run_at(T0 + timedelta(hours=5)), 0)

    def test_only_due_incidents_escalate(self):
        early = self.trigger(T0, 'Early')
        late = self.trigger(T0 + timedelta(minutes=3), 'Late')

        self.assertEqual(self.run_at(T0 + timedelta(minutes=6)), 1)

        self.assertEqual((paged(early), paged(late)), (['linus', 'grace'], ['linus']))

    def test_nobody_on_call_is_noted_on_the_timeline(self):
        empty = make_schedule(self.team, 'Empty')
        self.service.escalation_policy = make_policy(self.team, [empty])
        self.service.save()

        incident = self.trigger()

        self.assertEqual(paged(incident), [])
        self.assertTrue(incident.timeline.filter(message='Nobody is on call for Empty (level 1).').exists())

    def test_targets_who_left_the_team_are_skipped(self):
        self.team.memberships.filter(user=self.linus).delete()

        incident = self.trigger()

        self.assertEqual(paged(incident), [])
        self.assertTrue(incident.timeline.filter(message__startswith='Skipped linus').exists())

    def test_services_without_a_policy_or_levels_page_nobody(self):
        no_policy = make_service(self.team, 'Batch jobs')
        no_levels = make_service(self.team, 'Reports', make_policy(self.team, [], name='Empty policy'))

        for service in (no_policy, no_levels):
            with at(T0), self.captureOnCommitCallbacks(execute=True):
                incident, _ = incidents.trigger(service, 'Broken', 'warning')
            self.assertEqual(paged(incident), [])
            self.assertFalse(EscalationState.objects.filter(incident=incident).exists())
            self.assertTrue(incident.timeline.filter(kind='paged', message__contains='nobody was paged').exists())

    def test_run_escalations_command(self):
        self.trigger()
        out = StringIO()

        with at(T0 + timedelta(minutes=5)), self.captureOnCommitCallbacks(execute=True):
            call_command('run_escalations', stdout=out)

        self.assertEqual(out.getvalue().strip(), '1 incident(s) escalated.')
        self.assertEqual(len(mail.outbox), 2)


class PolicyRuleTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.policy = services.create_policy(self.team, self.owner, 'Default')

    def test_levels_are_numbered_in_order_and_renumbered_on_removal(self):
        schedule = make_schedule(self.team)
        first = services.add_level(self.policy, self.owner, 5, target_user=self.owner)
        services.add_level(self.policy, self.owner, 10, target_schedule=schedule)
        services.add_level(self.policy, self.owner, 15, target_user=self.owner)

        services.remove_level(first, self.owner)

        positions = list(self.policy.levels.values_list('position', 'delay_minutes'))
        self.assertEqual(positions, [(0, 10), (1, 15)])

    def test_a_level_has_exactly_one_target_from_the_team(self):
        with self.assertRaisesMessage(services.EscalationError, 'either a person or a schedule'):
            services.add_level(self.policy, self.owner, 5)
        with self.assertRaisesMessage(services.EscalationError, 'either a person or a schedule'):
            services.add_level(self.policy, self.owner, 5, target_user=self.owner, target_schedule=make_schedule(self.team))
        with self.assertRaisesMessage(services.EscalationError, 'is not a member'):
            services.add_level(self.policy, self.owner, 5, target_user=make_user())
        with self.assertRaisesMessage(services.EscalationError, 'another team'):
            services.add_level(self.policy, self.owner, 5, target_schedule=make_schedule())

    def test_the_database_enforces_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EscalationLevel.objects.create(policy=self.policy, position=0, delay_minutes=5)

    def test_responders_cannot_change_policies(self):
        responder = add_member(self.team)

        with self.assertRaises(TeamPermissionDenied):
            services.add_level(self.policy, responder, 5, target_user=responder)
        with self.assertRaises(TeamPermissionDenied):
            services.create_policy(self.team, responder, 'Mine')

    def test_policy_views(self):
        responder = add_member(self.team, make_user('linus'))
        self.client.force_login(self.owner)

        self.client.post(reverse('escalation:level_add', args=[self.policy.pk]),
                         {'target_user': responder.pk, 'delay_minutes': 7})
        detail = self.client.get(self.policy.get_absolute_url())
        self.client.force_login(responder)
        forbidden = self.client.post(reverse('escalation:level_add', args=[self.policy.pk]),
                                     {'target_user': responder.pk, 'delay_minutes': 7})

        self.assertEqual(list(self.policy.levels.values_list('target_user', 'delay_minutes')), [(responder.pk, 7)])
        self.assertContains(detail, 'Level 1:')
        self.assertEqual(forbidden.status_code, 403)

    def test_create_policy_view(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse('escalation:policy_create', args=[self.team.slug]),
                                    {'name': 'Night shift', 'description': '', 'repeat_count': 2})

        policy = self.team.escalation_policies.get(name='Night shift')
        self.assertRedirects(response, policy.get_absolute_url())
        self.assertEqual(policy.repeat_count, 2)


@skipUnless(connection.vendor == 'postgresql', 'needs row locks (run with DATABASE_URL=postgres://...)')
class SkipLockedTests(TransactionTestCase):
    def test_a_locked_incident_is_skipped_by_another_worker(self):
        team = make_team()
        responder = add_member(team)
        policy = make_policy(team, [responder, responder])
        service = make_service(team, policy=policy)
        states = []
        for summary in ('Locked elsewhere', 'Free'):
            incident = make_incident(service, summary=summary)
            states.append(EscalationState.objects.create(incident=incident, policy=policy, next_run_at=T0))
        locked, free = states
        holding, release = threading.Event(), threading.Event()

        def other_worker():
            try:
                with transaction.atomic():
                    EscalationState.objects.select_for_update().get(pk=locked.pk)
                    holding.set()
                    release.wait(10)
            finally:
                connection.close()

        thread = threading.Thread(target=other_worker)
        thread.start()
        holding.wait(10)
        try:
            first_pass = services.run_due(now=T0 + timedelta(minutes=1))
        finally:
            release.set()
            thread.join()
        second_pass = services.run_due(now=T0 + timedelta(minutes=1))

        self.assertEqual((first_pass, second_pass), (1, 1))
        self.assertEqual(paged(free.incident), [responder.username])
        self.assertEqual(paged(locked.incident), [responder.username])
