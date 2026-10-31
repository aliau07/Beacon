import os
from datetime import UTC, datetime, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.core.tests.factories import (
    TemporaryMediaMixin, add_member, image_upload, make_service, make_team, make_user, owner_of,
)
from apps.incidents import services as incidents
from apps.teams.services import TeamPermissionDenied

from . import services
from .models import Postmortem

T0 = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


class PostmortemMixin(TemporaryMediaMixin):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.linus = add_member(self.team, make_user('linus', first_name='Linus', last_name='T'))
        service = make_service(self.team, 'Search')
        with mock.patch('django.utils.timezone.now', return_value=T0):
            self.incident, _ = incidents.trigger(service, 'Search p99 above 2s', 'error', dedup_key='p99')
        with mock.patch('django.utils.timezone.now', return_value=T0 + timedelta(minutes=4)):
            incidents.acknowledge(self.incident, self.linus, via='Beacon')
        with mock.patch('django.utils.timezone.now', return_value=T0 + timedelta(minutes=95)):
            incidents.resolve(self.incident, self.linus, via='Beacon')


class PostmortemRuleTests(PostmortemMixin, TestCase):
    def test_only_resolved_incidents_get_one_postmortem(self):
        open_incident, _ = incidents.trigger(make_service(self.team), 'Still broken', 'critical')

        with self.assertRaisesMessage(services.PostmortemError, 'Resolve the incident'):
            services.start_postmortem(open_incident, self.owner)
        services.start_postmortem(self.incident, self.owner)
        with self.assertRaisesMessage(services.PostmortemError, 'already has a postmortem'):
            services.start_postmortem(self.incident, self.owner)

    def test_timeline_and_impact_are_filled_in_from_the_incident(self):
        postmortem = services.start_postmortem(self.incident, self.linus)

        events = list(postmortem.events.values_list('occurred_at', 'description'))
        self.assertEqual(events, [
            (T0, 'Triggered via the events API: Search p99 above 2s'),
            (T0 + timedelta(minutes=4), 'Acknowledged by Linus T.'),
            (T0 + timedelta(minutes=95), 'Resolved by Linus T.'),
        ])
        self.assertEqual(postmortem.title, 'Postmortem: Search p99 above 2s')
        self.assertIn('Service: Search', postmortem.impact)
        self.assertIn('Open for 1h 35m', postmortem.impact)
        self.assertIn('Acknowledged after 4m', postmortem.impact)

    def test_action_items_need_team_owners_and_can_be_ticked_off(self):
        postmortem = services.start_postmortem(self.incident, self.linus)

        item = services.add_action_item(postmortem, self.linus, 'Rebuild indexes on a standby', owner=self.linus)
        with self.assertRaisesMessage(services.PostmortemError, 'is not on'):
            services.add_action_item(postmortem, self.linus, 'Outsourced', owner=make_user())
        services.toggle_action_item(item, self.linus)
        self.assertTrue(item.is_done)
        services.toggle_action_item(item, self.linus)
        self.assertFalse(item.is_done)

    def test_publishing_needs_a_root_cause(self):
        postmortem = services.start_postmortem(self.incident, self.linus)

        with self.assertRaises(services.PostmortemError):
            services.publish(postmortem, self.linus)
        services.update_postmortem(postmortem, self.linus, postmortem.title, postmortem.impact, 'Disk saturation.')
        services.publish(postmortem, self.linus)
        self.assertEqual(postmortem.status, Postmortem.Status.PUBLISHED)

    def test_screenshots_are_resized_and_stripped_of_exif(self):
        postmortem = services.start_postmortem(self.incident, self.linus)
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'
        exif[0x0132] = '2026:03:02 12:00:00'

        screenshot = services.add_screenshot(postmortem, self.linus, image_upload('graph.jpg', size=(4000, 2000), exif=exif),
                                             'p99 latency')

        with Image.open(screenshot.image.path) as image:
            self.assertEqual(image.size, (1600, 800))
            self.assertEqual(len(image.getexif()), 0)
        path = screenshot.image.path
        services.delete_screenshot(screenshot, self.linus)
        self.assertFalse(os.path.exists(path))

    def test_bad_uploads_and_outsiders_are_rejected(self):
        postmortem = services.start_postmortem(self.incident, self.linus)

        with self.assertRaisesMessage(services.PostmortemError, 'JPEG, PNG, WebP or GIF'):
            services.add_screenshot(postmortem, self.linus, image_upload('old.bmp', image_format='BMP'))
        with self.assertRaises(TeamPermissionDenied):
            services.add_event(postmortem, make_user(), T0, 'Sneaky edit')


class PostmortemViewTests(PostmortemMixin, TestCase):
    def test_start_from_the_incident_page(self):
        self.client.force_login(self.linus)

        response = self.client.post(reverse('postmortems:start', args=[self.incident.pk]))

        postmortem = Postmortem.objects.get()
        self.assertRedirects(response, reverse('postmortems:edit', args=[postmortem.pk]))
        self.assertContains(self.client.get(self.incident.get_absolute_url()), postmortem.get_absolute_url())

    def test_edit_upload_and_action_item_views(self):
        postmortem = services.start_postmortem(self.incident, self.linus)
        self.client.force_login(self.owner)

        self.client.post(reverse('postmortems:edit', args=[postmortem.pk]),
                         {'title': 'Slow search', 'impact': 'Search was slow.', 'root_cause': 'A full reindex.'})
        self.client.post(reverse('postmortems:screenshot_add', args=[postmortem.pk]),
                         {'image': image_upload('graph.png', image_format='PNG'), 'caption': 'Latency'})
        self.client.post(reverse('postmortems:action_add', args=[postmortem.pk]),
                         {'description': 'Alert on I/O wait', 'owner': self.linus.pk, 'due_date': ''})
        page = self.client.get(postmortem.get_absolute_url())

        self.assertContains(page, 'A full reindex.')
        self.assertContains(page, 'Alert on I/O wait')
        self.assertEqual(postmortem.screenshots.get().caption, 'Latency')
        self.assertTrue(postmortem.screenshots.get().image.name.endswith('.png'))

    def test_outsiders_get_404(self):
        postmortem = services.start_postmortem(self.incident, self.linus)
        self.client.force_login(make_user())

        self.assertEqual(self.client.get(postmortem.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse('postmortems:start', args=[self.incident.pk])).status_code, 404)
