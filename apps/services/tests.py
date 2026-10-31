import hashlib

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.factories import add_member, make_api_key, make_policy, make_service, make_team, make_user, owner_of
from apps.teams.services import Role, TeamPermissionDenied

from . import services
from .models import ApiKey, Service


class ApiKeyTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.service = make_service(self.team, 'Checkout API')

    def test_only_the_prefix_and_sha256_hash_are_stored(self):
        api_key, raw_key = services.create_api_key(self.service, self.owner, ' Alertmanager ')

        self.assertTrue(raw_key.startswith(api_key.prefix + '_'))
        self.assertRegex(api_key.prefix, r'^bcn_[0-9a-f]{8}$')
        self.assertEqual(api_key.key_hash, hashlib.sha256(raw_key.encode()).hexdigest())
        self.assertEqual(api_key.name, 'Alertmanager')
        stored = ApiKey.objects.filter(pk=api_key.pk).values().get()
        for value in stored.values():
            self.assertNotEqual(value, raw_key)
            self.assertNotIn(raw_key, str(value))

    def test_authenticate_accepts_the_full_key_only(self):
        api_key, raw_key = make_api_key(self.service)

        self.assertEqual(services.authenticate(raw_key), api_key)
        self.assertIsNone(services.authenticate(raw_key[:-1] + ('A' if raw_key[-1] != 'A' else 'B')))
        self.assertIsNone(services.authenticate(api_key.prefix))
        self.assertIsNone(services.authenticate(api_key.key_hash))

    def test_authenticate_rejects_malformed_and_revoked_keys(self):
        api_key, raw_key = make_api_key(self.service)

        for bad in (None, '', 'not-a-beacon-key', 'bcn_' + 'x' * 200):
            self.assertIsNone(services.authenticate(bad))
        services.revoke_api_key(api_key, self.owner)
        self.assertIsNone(services.authenticate(raw_key))

    def test_authenticate_records_last_use(self):
        api_key, raw_key = make_api_key(self.service)

        services.authenticate(raw_key)

        api_key.refresh_from_db()
        self.assertAlmostEqual(api_key.last_used_at.timestamp(), timezone.now().timestamp(), delta=5)

    def test_responders_cannot_create_or_revoke_keys(self):
        responder = add_member(self.team)
        api_key, _ = make_api_key(self.service)

        with self.assertRaises(TeamPermissionDenied):
            services.create_api_key(self.service, responder, 'Mine')
        with self.assertRaises(TeamPermissionDenied):
            services.revoke_api_key(api_key, responder)


class ServiceRuleTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)

    def test_admins_create_services(self):
        admin = add_member(self.team, role=Role.ADMIN)
        policy = make_policy(self.team, [admin])

        service = services.create_service(self.team, admin, ' Search ', 'Product search', policy)

        self.assertEqual((service.name, service.escalation_policy), ('Search', policy))

    def test_responders_cannot_create_services(self):
        with self.assertRaises(TeamPermissionDenied):
            services.create_service(self.team, add_member(self.team), 'Search')

    def test_names_are_unique_per_team_and_policies_must_be_the_teams(self):
        services.create_service(self.team, self.owner, 'Search')
        other_policy = make_policy(make_team(), [make_user()])

        with self.assertRaisesMessage(services.ServiceError, 'already has a service'):
            services.create_service(self.team, self.owner, 'search')
        with self.assertRaisesMessage(services.ServiceError, 'another team'):
            services.create_service(self.team, self.owner, 'Payments', escalation_policy=other_policy)
        services.create_service(make_team(owner=self.owner), self.owner, 'Search')  # another team may reuse the name


class ServiceViewTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.service = make_service(self.team, 'Checkout API')

    def test_new_key_is_shown_once(self):
        self.client.force_login(self.owner)

        created = self.client.post(reverse('services:api_key_create', args=[self.service.pk]), {'name': 'Grafana'})
        raw_key = created.context['new_raw_key']
        later = self.client.get(self.service.get_absolute_url())

        self.assertContains(created, raw_key)
        self.assertContains(created, "won't be shown again")
        self.assertIn('no-store', created['Cache-Control'])
        self.assertNotContains(later, raw_key)
        self.assertContains(later, ApiKey.objects.get().prefix)
        self.assertEqual(services.authenticate(raw_key).service, self.service)

    def test_revoke_view(self):
        api_key, raw_key = make_api_key(self.service)
        self.client.force_login(self.owner)

        self.client.post(reverse('services:api_key_revoke', args=[api_key.pk]))

        self.assertIsNone(services.authenticate(raw_key))

    def test_responders_see_keys_but_cannot_create_them(self):
        responder = add_member(self.team)
        self.client.force_login(responder)

        detail = self.client.get(self.service.get_absolute_url())
        create = self.client.post(reverse('services:api_key_create', args=[self.service.pk]), {'name': 'Mine'})

        self.assertNotContains(detail, 'New API key')
        self.assertEqual(create.status_code, 403)
        self.assertFalse(ApiKey.objects.exists())

    def test_service_pages_are_404_for_outsiders(self):
        self.client.force_login(make_user())

        self.assertEqual(self.client.get(self.service.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse('services:api_key_create', args=[self.service.pk]), {'name': 'x'}).status_code, 404)

    def test_create_and_edit_service_views(self):
        policy = make_policy(self.team, [self.owner])
        self.client.force_login(self.owner)

        self.client.post(reverse('services:create', args=[self.team.slug]), {'name': 'Search', 'description': '',
                                                                           'escalation_policy': policy.pk})
        search = Service.objects.get(name='Search')
        self.client.post(reverse('services:edit', args=[search.pk]), {'name': 'Search v2', 'description': 'New',
                                                                      'escalation_policy': ''})

        search.refresh_from_db()
        self.assertEqual((search.name, search.escalation_policy), ('Search v2', None))
