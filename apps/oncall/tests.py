from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.factories import (
    add_member, make_override, make_rotation, make_schedule, make_team, make_user, owner_of,
)
from apps.teams.services import Role, TeamPermissionDenied

from . import services
from .models import Override, Rotation


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class RotationBasicsTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.alice, self.bob, self.carol = make_user('alice'), make_user('bob'), make_user('carol')
        self.schedule = make_schedule(self.team)

    def test_weekly_rotation_takes_turns_and_wraps(self):
        rotation = make_rotation(self.schedule, [self.alice, self.bob, self.carol], start_date=date(2026, 1, 5))

        on_call = []
        for week in range(4):
            on_call.append(services.who_is_on_call(self.schedule, utc(2026, 1, 5, 12) + timedelta(weeks=week)))

        self.assertEqual(on_call, [self.alice, self.bob, self.carol, self.alice])
        shift = services.shift_at(rotation, utc(2026, 1, 14, 12))
        self.assertEqual((shift.index, shift.starts_at, shift.ends_at), (1, utc(2026, 1, 12, 9), utc(2026, 1, 19, 9)))

    def test_daily_and_multi_day_shifts(self):
        make_rotation(self.schedule, [self.alice, self.bob], shift_length_days=2, start_date=date(2026, 1, 1))

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 2, 23)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 3, 9)), self.bob)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 5, 9)), self.alice)

    def test_handoff_happens_exactly_at_the_handoff_time(self):
        make_rotation(self.schedule, [self.alice, self.bob], shift_length_days=1, start_date=date(2026, 1, 1))

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 2, 8, 59, 59)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 2, 9)), self.bob)

    def test_nobody_before_the_first_handoff_or_without_participants(self):
        make_rotation(self.schedule, [self.alice], start_date=date(2026, 1, 5))
        empty = make_schedule(self.team)
        make_rotation(empty, [], start_date=date(2026, 1, 5))

        self.assertIsNone(services.who_is_on_call(self.schedule, utc(2026, 1, 5, 8, 59)))
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 1, 5, 9)), self.alice)
        self.assertIsNone(services.who_is_on_call(empty, utc(2026, 2, 1)))

    def test_higher_priority_layers_win_once_they_start(self):
        make_rotation(self.schedule, [self.alice], start_date=date(2026, 1, 5), priority=1, name='Base')
        make_rotation(self.schedule, [self.bob], start_date=date(2026, 3, 2), priority=2, name='New team')

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 15)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 3)), self.bob)


class DaylightSavingTests(TestCase):
    """Handoffs stay at the local clock time; the UTC instant moves when the clocks change."""

    def setUp(self):
        self.alice, self.bob = make_user('alice'), make_user('bob')
        self.schedule = make_schedule()

    def rotation(self, time_zone, start_date, handoff_time=time(9, 0), shift_length_days=7):
        return make_rotation(self.schedule, [self.alice, self.bob], time_zone=time_zone, start_date=start_date,
                             handoff_time=handoff_time, shift_length_days=shift_length_days)

    def test_new_york_weekly_handoff_moves_an_hour_earlier_in_utc_when_dst_starts(self):
        # DST starts in New York on Sunday 8 March 2026. 09:00 EST is 14:00 UTC; 09:00 EDT is 13:00 UTC.
        rotation = self.rotation('America/New_York', date(2026, 3, 2))

        self.assertEqual(services.handoff_at(rotation, date(2026, 3, 2)), utc(2026, 3, 2, 14))
        self.assertEqual(services.handoff_at(rotation, date(2026, 3, 9)), utc(2026, 3, 9, 13))
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 9, 12, 59)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 9, 13, 0)), self.bob)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 9, 13, 30)), self.bob)

    def test_dublin_weekly_handoff_moves_an_hour_later_in_utc_when_summer_time_ends(self):
        # Irish summer time ends on Sunday 25 October 2026. 09:00 IST is 08:00 UTC; 09:00 GMT is 09:00 UTC.
        rotation = self.rotation('Europe/Dublin', date(2026, 10, 19))

        self.assertEqual(services.shift_at(rotation, utc(2026, 10, 20)).starts_at, utc(2026, 10, 19, 8))
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 10, 26, 8, 30)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 10, 26, 9)), self.bob)

    def test_daily_handoffs_keep_local_time_and_the_dst_shift_is_23_hours(self):
        rotation = self.rotation('America/New_York', date(2026, 3, 1), shift_length_days=1)
        new_york = ZoneInfo('America/New_York')

        handoffs = services.handoffs_between(rotation, utc(2026, 3, 6), utc(2026, 3, 11))

        local_times, utc_hours = [], []
        for moment in handoffs:
            local_times.append(moment.astimezone(new_york).time())
            utc_hours.append(moment.hour)
        self.assertEqual(local_times, [time(9, 0)] * 5)
        self.assertEqual(utc_hours, [14, 14, 13, 13, 13])
        dst_shift = services.shift_at(rotation, utc(2026, 3, 7, 20))
        self.assertEqual(dst_shift.ends_at - dst_shift.starts_at, timedelta(hours=23))

    def test_no_flip_flop_in_the_repeated_hour_when_clocks_go_back(self):
        # New York falls back on Sunday 1 November 2026: 01:00-02:00 happens twice (EDT, then EST).
        self.rotation('America/New_York', date(2026, 10, 30), handoff_time=time(1, 30), shift_length_days=1)

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 11, 1, 5, 29)), self.bob)    # 01:29 EDT
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 11, 1, 5, 30)), self.alice)  # 01:30 EDT
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 11, 1, 6, 15)), self.alice)  # 01:15 EST
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 11, 2, 6, 29)), self.alice)  # 01:29 EST
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 11, 2, 6, 30)), self.bob)    # 01:30 EST

    def test_a_handoff_time_skipped_by_spring_forward_happens_on_the_old_offset(self):
        # 02:30 does not exist in New York on 8 March 2026; it is read as 02:30 EST = 07:30 UTC (03:30 EDT).
        rotation = self.rotation('America/New_York', date(2026, 3, 7), handoff_time=time(2, 30), shift_length_days=1)

        self.assertEqual(services.handoff_at(rotation, date(2026, 3, 8)), utc(2026, 3, 8, 7, 30))
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 8, 7, 29)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 3, 8, 7, 30)), self.bob)
        self.assertEqual(services.handoff_at(rotation, date(2026, 3, 9)), utc(2026, 3, 9, 6, 30))


class OverrideTests(TestCase):
    def setUp(self):
        self.alice, self.bob, self.carol = make_user('alice'), make_user('bob'), make_user('carol')
        self.schedule = make_schedule()
        make_rotation(self.schedule, [self.alice], start_date=date(2026, 1, 5))

    def test_overrides_win_and_end_exclusively(self):
        make_override(self.schedule, self.bob, utc(2026, 2, 3, 12), utc(2026, 2, 3, 18))

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 11, 59)), self.alice)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 12)), self.bob)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 17, 59)), self.bob)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 18)), self.alice)

    def test_overrides_apply_even_without_any_rotation(self):
        bare = make_schedule()
        make_override(bare, self.bob, utc(2026, 2, 3, 12), utc(2026, 2, 3, 18))

        self.assertEqual(services.who_is_on_call(bare, utc(2026, 2, 3, 13)), self.bob)
        self.assertIsNone(services.who_is_on_call(bare, utc(2026, 2, 3, 19)))

    def test_the_most_recent_overlapping_override_wins(self):
        make_override(self.schedule, self.bob, utc(2026, 2, 3, 12), utc(2026, 2, 3, 18))
        make_override(self.schedule, self.carol, utc(2026, 2, 3, 15), utc(2026, 2, 3, 20))

        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 14)), self.bob)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 16)), self.carol)
        self.assertEqual(services.who_is_on_call(self.schedule, utc(2026, 2, 3, 19)), self.carol)

    def test_final_schedule_merges_rotations_and_overrides(self):
        schedule = make_schedule()
        make_rotation(schedule, [self.alice, self.bob], shift_length_days=1, start_date=date(2026, 3, 1))
        make_override(schedule, self.carol, utc(2026, 3, 2, 12), utc(2026, 3, 2, 15))

        segments = services.final_schedule(schedule, utc(2026, 3, 2), utc(2026, 3, 3))

        rows = []
        for segment in segments:
            rows.append((segment.starts_at.hour, segment.ends_at.hour, segment.user.username, segment.source))
        self.assertEqual(rows, [(0, 9, 'alice', 'Primary'), (9, 12, 'bob', 'Primary'), (12, 15, 'carol', 'override'),
                                (15, 0, 'bob', 'Primary')])

    def test_on_call_now_says_until_when(self):
        current = services.on_call_now(self.schedule, utc(2026, 1, 7, 12))

        # alice is the only participant, so her weekly shifts merge up to the 31-day look-ahead
        self.assertEqual((current.user, current.ends_at), (self.alice, utc(2026, 2, 7, 12)))
        self.assertIsNone(services.on_call_now(make_schedule(), utc(2026, 1, 7)))


class ScheduleRuleTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.responder = add_member(self.team, make_user('linus'))
        self.schedule = make_schedule(self.team)
        self.soon = timezone.now() + timedelta(hours=1)

    def rotation_fields(self, **overrides):
        fields = dict(name='Weekly', time_zone='Europe/Dublin', start_date=date(2026, 1, 5), handoff_time=time(9),
                      shift_length_days=7, priority=1)
        fields.update(overrides)
        return fields

    def test_rotation_participants_must_be_team_members(self):
        with self.assertRaisesMessage(services.OnCallError, 'is not a member'):
            services.save_rotation(self.schedule, self.owner, [self.responder, make_user('stranger')], **self.rotation_fields())
        with self.assertRaisesMessage(services.OnCallError, 'at least one participant'):
            services.save_rotation(self.schedule, self.owner, [], **self.rotation_fields())

    def test_save_rotation_keeps_participant_order_and_validates_the_time_zone(self):
        rotation = services.save_rotation(self.schedule, self.owner, [self.responder, self.owner, self.responder],
                                          **self.rotation_fields())

        order = []
        for participant in rotation.participants.all():
            order.append(participant.user)
        self.assertEqual(order, [self.responder, self.owner, self.responder])
        with self.assertRaises(Exception):
            services.save_rotation(self.schedule, self.owner, [self.owner], **self.rotation_fields(time_zone='Mars/Base'))

    def test_responders_cannot_change_rotations_or_schedules(self):
        with self.assertRaises(TeamPermissionDenied):
            services.save_rotation(self.schedule, self.responder, [self.responder], **self.rotation_fields())
        with self.assertRaises(TeamPermissionDenied):
            services.create_schedule(self.team, self.responder, 'Mine')

    def test_responders_may_only_override_for_themselves(self):
        services.create_override(self.schedule, self.responder, self.responder, self.soon, self.soon + timedelta(hours=2))
        with self.assertRaisesMessage(services.OnCallError, 'only create overrides for themselves'):
            services.create_override(self.schedule, self.responder, self.owner, self.soon, self.soon + timedelta(hours=2))
        services.create_override(self.schedule, self.owner, self.responder, self.soon, self.soon + timedelta(hours=2))
        self.assertEqual(Override.objects.count(), 2)

    def test_override_times_are_checked(self):
        past = timezone.now() - timedelta(days=2)
        cases = [
            (self.soon, self.soon, 'must end after it starts'),
            (past, past + timedelta(hours=1), 'entirely in the past'),
            (self.soon, self.soon + timedelta(days=32), 'at most 31 days'),
        ]
        for starts_at, ends_at, message in cases:
            with self.subTest(message=message), self.assertRaisesMessage(services.OnCallError, message):
                services.create_override(self.schedule, self.owner, self.owner, starts_at, ends_at)
        with self.assertRaisesMessage(services.OnCallError, 'is not a member'):
            services.create_override(self.schedule, self.owner, make_user(), self.soon, self.soon + timedelta(hours=1))

    def test_who_may_delete_an_override(self):
        other = add_member(self.team)
        override = services.create_override(self.schedule, self.owner, self.responder, self.soon, self.soon + timedelta(hours=1))

        with self.assertRaises(services.OnCallError):
            services.delete_override(override, other)
        services.delete_override(override, self.responder)
        self.assertFalse(Override.objects.exists())


class ScheduleViewTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.grace = add_member(self.team, make_user('grace', first_name='Grace', last_name='Hopper'))
        self.schedule = make_schedule(self.team, 'Primary on-call')

    def test_detail_shows_who_is_on_call_now(self):
        make_rotation(self.schedule, [self.grace], start_date=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.owner)

        response = self.client.get(self.schedule.get_absolute_url())

        self.assertEqual(response.context['current'].user, self.grace)
        self.assertContains(response, 'Grace Hopper')
        self.assertContains(self.client.get(reverse('oncall:now')), 'Grace Hopper')
        self.assertContains(self.client.get(reverse('oncall:schedule_list', args=[self.team.slug])), 'Grace Hopper')

    def test_rotation_form_takes_usernames_in_order(self):
        self.client.force_login(self.owner)
        url = reverse('oncall:rotation_create', args=[self.schedule.pk])
        data = {'name': 'Weekly', 'time_zone': 'America/New_York', 'start_date': '2026-03-02', 'handoff_time': '09:00',
                'shift_length_days': 7, 'priority': 1, 'participant_names': f'grace, {self.owner.username}\nGRACE'}

        bad = self.client.post(url, {**data, 'participant_names': 'grace, nobody'})
        self.client.post(url, data)

        self.assertContains(bad, 'nobody')
        rotation = Rotation.objects.get()
        usernames = []
        for participant in rotation.participants.select_related('user'):
            usernames.append(participant.user.username)
        self.assertEqual(usernames, ['grace', self.owner.username, 'grace'])
        self.assertEqual(rotation.time_zone, 'America/New_York')

    def test_responders_get_403_on_rotation_forms_but_can_add_their_own_override(self):
        self.client.force_login(self.grace)
        starts = timezone.localtime() + timedelta(hours=1)

        forbidden = self.client.get(reverse('oncall:rotation_create', args=[self.schedule.pk]))
        self.client.post(reverse('oncall:override_create', args=[self.schedule.pk]), {
            'user': self.grace.pk, 'starts_at': starts.strftime('%Y-%m-%dT%H:%M'),
            'ends_at': (starts + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'), 'reason': 'Swap with Ada',
        })

        self.assertEqual(forbidden.status_code, 403)
        override = Override.objects.get()
        self.assertEqual((override.user, override.created_by, override.reason), (self.grace, self.grace, 'Swap with Ada'))

    def test_override_times_are_read_in_the_users_time_zone(self):
        self.grace.time_zone = 'Asia/Tokyo'
        self.grace.save()
        self.client.force_login(self.grace)
        tomorrow = (timezone.now() + timedelta(days=1)).astimezone(ZoneInfo('Asia/Tokyo')).date()

        self.client.post(reverse('oncall:override_create', args=[self.schedule.pk]), {
            'user': self.grace.pk, 'starts_at': f'{tomorrow}T09:00', 'ends_at': f'{tomorrow}T12:00',
        })

        override = Override.objects.get()
        self.assertEqual(override.starts_at, datetime.combine(tomorrow, time(9), tzinfo=ZoneInfo('Asia/Tokyo')))

    def test_outsiders_get_404(self):
        self.client.force_login(make_user())

        self.assertEqual(self.client.get(self.schedule.get_absolute_url()).status_code, 404)
