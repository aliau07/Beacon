from django.test import TestCase
from django.urls import reverse

from apps.core.tests.factories import add_member, make_incident, make_service, make_team, make_user, owner_of
from apps.incidents.models import Incident
from apps.teams.services import TeamPermissionDenied

from . import services
from .models import Component, ComponentStatus, StatusPage


class ComponentStatusTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.api, self.worker = make_service(self.team, 'API'), make_service(self.team, 'Worker')
        self.page = StatusPage.objects.create(team=self.team, title='Acme status', slug='acme')
        self.checkout = services.save_component(self.page, self.owner, 'Checkout', [self.api, self.worker])

    def status(self, component=None):
        return services.component_status(component or self.checkout)

    def test_operational_without_open_incidents(self):
        self.assertEqual(self.status(), ComponentStatus.OPERATIONAL)

    def test_each_severity_maps_to_a_status(self):
        expected = {'critical': 'major_outage', 'error': 'partial_outage', 'warning': 'degraded', 'info': 'minor'}
        for severity, status in expected.items():
            with self.subTest(severity=severity):
                incident = make_incident(self.api, severity=severity)
                self.assertEqual(self.status(), status)
                incident.delete()

    def test_the_worst_open_severity_across_linked_services_wins(self):
        make_incident(self.api, severity='warning')
        make_incident(self.worker, severity='critical', status=Incident.Status.ACKNOWLEDGED)
        make_incident(self.api, severity='info')

        self.assertEqual(self.status(), ComponentStatus.MAJOR_OUTAGE)

    def test_resolved_incidents_and_unlinked_services_do_not_count(self):
        make_incident(self.api, severity='critical', status=Incident.Status.RESOLVED)
        make_incident(make_service(self.team, 'Unlinked'), severity='critical')

        self.assertEqual(self.status(), ComponentStatus.OPERATIONAL)

    def test_a_manual_override_wins_until_cleared(self):
        make_incident(self.api, severity='critical')

        services.set_override(self.checkout, self.owner, ComponentStatus.MAINTENANCE, 'Planned database upgrade')
        self.assertEqual(self.status(), ComponentStatus.MAINTENANCE)
        services.set_override(self.checkout, self.owner, '', 'ignored when clearing')
        self.checkout.refresh_from_db()
        self.assertEqual((self.status(), self.checkout.override_message), (ComponentStatus.MAJOR_OUTAGE, ''))

    def test_summary_reports_the_worst_component_overall(self):
        search = services.save_component(self.page, self.owner, 'Search', [make_service(self.team, 'Search')], position=2)
        make_incident(self.api, severity='warning')
        services.set_override(search, self.owner, ComponentStatus.PARTIAL_OUTAGE, 'Index rebuild')

        summary = services.summary(self.page)

        self.assertEqual((summary['status'], summary['status_label']), ('partial_outage', 'Partial outage'))
        rows = []
        for row in summary['components']:
            rows.append((row['name'], row['status'], row['overridden'], row['message']))
        self.assertEqual(rows, [('Checkout', 'degraded', False, ''), ('Search', 'partial_outage', True, 'Index rebuild')])
        self.assertEqual(summary['refresh_seconds'], 30)

    def test_rules_for_changing_the_page(self):
        with self.assertRaises(TeamPermissionDenied):
            services.save_component(self.page, add_member(self.team), 'Mine', [])
        with self.assertRaisesMessage(services.StatusPageError, 'belongs to another team'):
            services.save_component(self.page, self.owner, 'Theirs', [make_service()])
        StatusPage.objects.create(team=make_team(), title='Other', slug='taken')
        with self.assertRaisesMessage(services.StatusPageError, 'taken'):
            services.save_page(self.team, self.owner, 'Acme', 'taken')


class PublicPageTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.service = make_service(self.team, 'API')
        self.page = StatusPage.objects.create(team=self.team, title='Acme status', slug='acme')
        component = Component.objects.create(status_page=self.page, name='Public API')
        component.services.add(self.service)

    def test_public_page_needs_no_login_and_refreshes_every_30_seconds(self):
        make_incident(self.service, severity='critical', summary='Internal detail: db1 disk full')

        response = self.client.get(reverse('statuspage:public', args=['acme']))

        self.assertContains(response, 'Major outage')
        self.assertContains(response, 'Public API')
        self.assertContains(response, 'data-refresh-seconds="30"')
        self.assertContains(response, 'data-status-url="/status/acme/summary.json"')
        self.assertContains(response, 'statuspage/js/refresh.js')
        self.assertNotContains(response, 'db1 disk full')

    def test_json_summary(self):
        make_incident(self.service, severity='warning')

        body = self.client.get(reverse('statuspage:public_summary', args=['acme'])).json()

        self.assertEqual(body['status'], 'degraded')
        self.assertEqual(body['components'][0]['status_label'], 'Degraded performance')

    def test_hidden_pages_are_404(self):
        self.page.is_public = False
        self.page.save()

        self.assertEqual(self.client.get(reverse('statuspage:public', args=['acme'])).status_code, 404)
        self.assertEqual(self.client.get(reverse('statuspage:public_summary', args=['acme'])).status_code, 404)

    def test_refresh_script_fetches_on_an_interval_and_avoids_inner_html(self):
        from django.contrib.staticfiles import finders

        with open(finders.find('statuspage/js/refresh.js')) as script:
            source = script.read()
        self.assertIn('setInterval(refresh, seconds * 1000)', source)
        self.assertIn('fetch(url', source)
        self.assertNotIn('innerHTML =', source)


class ManageViewTests(TestCase):
    def setUp(self):
        self.team = make_team()
        self.owner = owner_of(self.team)
        self.service = make_service(self.team, 'API')

    def test_admin_creates_the_page_and_a_component(self):
        self.client.force_login(self.owner)

        self.client.post(reverse('statuspage:manage', args=[self.team.slug]),
                         {'title': 'Acme status', 'slug': 'acme', 'description': '', 'is_public': 'on'})
        self.client.post(reverse('statuspage:component_add', args=[self.team.slug]),
                         {'name': 'API', 'description': '', 'position': 1, 'services': [self.service.pk],
                          'override_status': '', 'override_message': ''})

        component = Component.objects.get()
        self.assertEqual((component.status_page.slug, list(component.services.all())), ('acme', [self.service]))
        page = self.client.get(reverse('statuspage:manage', args=[self.team.slug]))
        self.assertContains(page, 'All systems operational')
        self.assertContains(page, (  # each service checkbox sits in its own Bootstrap .form-check row
            f'<div class="form-check"><input type="checkbox" name="services" value="{self.service.pk}" '
            'class="form-check-input" id="id_services_0"><label class="form-check-label" for="id_services_0">API</label></div>'
        ), html=True)

    def test_responders_can_look_but_not_change(self):
        StatusPage.objects.create(team=self.team, title='Acme status', slug='acme')
        responder = add_member(self.team)
        self.client.force_login(responder)

        view = self.client.get(reverse('statuspage:manage', args=[self.team.slug]))
        change = self.client.post(reverse('statuspage:manage', args=[self.team.slug]),
                                  {'title': 'Hacked', 'slug': 'acme', 'is_public': 'on'})

        self.assertEqual((view.status_code, change.status_code), (200, 403))
        self.assertEqual(StatusPage.objects.get().title, 'Acme status')
        self.assertEqual(self.client.get(reverse('statuspage:manage', args=[make_team().slug])).status_code, 404)

    def test_override_set_from_the_component_form(self):
        page = StatusPage.objects.create(team=self.team, title='Acme status', slug='acme')
        component = Component.objects.create(status_page=page, name='API')
        self.client.force_login(self.owner)

        self.client.post(reverse('statuspage:component_edit', args=[component.pk]), {
            'name': 'API', 'description': '', 'position': 0, 'services': [self.service.pk],
            'override_status': 'maintenance', 'override_message': 'Back at 18:00',
        })

        self.assertContains(self.client.get(reverse('statuspage:public', args=['acme'])), 'Back at 18:00')
        self.assertEqual(self.client.get(reverse('statuspage:public_summary', args=['acme'])).json()['status'], 'maintenance')
