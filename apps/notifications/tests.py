from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.factories import add_member, make_incident, make_service, make_team, make_user
from apps.incidents import services as incidents

from . import services
from .models import Notification


class NotificationTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.linus = add_member(self.team, make_user('linus'))
        self.incident = make_incident(make_service(self.team, 'Checkout API'), summary='Checkout failing', severity='critical')

    def test_a_page_lands_in_the_inbox_and_is_emailed_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            notification = services.page(self.linus, self.incident, 'Default, level 1')
            self.assertEqual(mail.outbox, [])

        self.assertEqual(notification.title, f'[Critical] #{self.incident.pk} Checkout failing')
        self.assertEqual(mail.outbox[0].subject, f'[Beacon] [Critical] #{self.incident.pk} Checkout failing')
        self.assertIn('Why you: Default, level 1', mail.outbox[0].body)
        self.assertIn(self.incident.get_absolute_url(), mail.outbox[0].body)

    def test_navbar_shows_the_unread_count(self):
        services.page(self.linus, self.incident, 'level 1')
        services.page(self.linus, self.incident, 'level 1, repeat 1')
        self.client.force_login(self.linus)

        response = self.client.get(reverse('notifications:inbox'))

        self.assertEqual(response.context['unread_notification_count'], 2)
        self.assertContains(response, 'title="Unread pages and updates">2</span>', html=False)

    def test_opening_marks_read_and_goes_to_the_incident(self):
        notification = services.page(self.linus, self.incident, 'level 1')
        self.client.force_login(self.linus)

        response = self.client.post(reverse('notifications:open', args=[notification.pk]))

        self.assertRedirects(response, self.incident.get_absolute_url())
        self.assertEqual(services.unread_count(self.linus), 0)

    def test_people_only_see_their_own_inbox(self):
        notification = services.page(self.linus, self.incident, 'level 1')
        self.client.force_login(make_user('nosy'))

        self.assertEqual(self.client.post(reverse('notifications:open', args=[notification.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('notifications:inbox')), 'Checkout failing')

    def test_mark_all_read(self):
        services.page(self.linus, self.incident, 'level 1')
        services.page(self.linus, self.incident, 'level 2')
        self.client.force_login(self.linus)

        response = self.client.post(reverse('notifications:mark_all_read'), follow=True)

        self.assertContains(response, '2 notifications marked as read.')
        self.assertFalse(Notification.objects.filter(read_at__isnull=True).exists())

    def test_people_who_were_paged_hear_when_it_is_resolved(self):
        grace = add_member(self.team, make_user('grace'))
        services.page(self.linus, self.incident, 'level 1')
        services.page(grace, self.incident, 'level 2')

        with self.captureOnCommitCallbacks(execute=True):
            incidents.resolve(self.incident, grace, via='Beacon')

        resolved = Notification.objects.filter(kind='resolved')
        self.assertEqual(list(resolved.values_list('recipient__username', flat=True)), ['linus'])
        self.assertEqual(mail.outbox[-1].to, ['linus@example.com'])
        self.assertIn('Resolved by grace', mail.outbox[-1].body)
