from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.factories import add_member, make_team, make_user, owner_of

from . import services
from .models import Membership, Team

Role = Membership.Role


class TeamRuleTests(TestCase):
    def setUp(self):
        self.team = make_team('Platform')
        self.owner = owner_of(self.team)
        self.admin = add_member(self.team, role=Role.ADMIN)
        self.responder = add_member(self.team)

    def membership(self, user):
        return Membership.objects.get(team=self.team, user=user)

    def test_create_team_makes_the_creator_owner_with_a_unique_slug(self):
        Team.objects.create(name='Other', slug='payments')
        team = services.create_team('Payments', self.responder)

        self.assertEqual(team.slug, 'payments-2')
        self.assertEqual(services.role_for(team, self.responder), Role.OWNER)
        with self.assertRaises(services.TeamError):
            services.create_team('payments', self.owner)

    def test_role_ranks(self):
        self.assertTrue(services.has_role(self.team, self.owner, Role.ADMIN))
        self.assertTrue(services.has_role(self.team, self.admin, Role.ADMIN))
        self.assertFalse(services.has_role(self.team, self.responder, Role.ADMIN))
        self.assertTrue(services.is_member(self.team, self.responder))
        self.assertFalse(services.is_member(self.team, make_user()))

    def test_admin_adds_members_and_they_are_emailed(self):
        newcomer = make_user('newcomer')

        services.add_member(self.team, self.admin, newcomer, Role.RESPONDER)

        self.assertTrue(services.is_member(self.team, newcomer))
        self.assertEqual(mail.outbox[0].to, ['newcomer@example.com'])
        self.assertIn('added you to Platform', mail.outbox[0].body)
        with self.assertRaises(services.TeamError):
            services.add_member(self.team, self.admin, newcomer)

    def test_responders_cannot_manage_members(self):
        with self.assertRaises(services.TeamPermissionDenied):
            services.add_member(self.team, self.responder, make_user())
        with self.assertRaises(services.TeamPermissionDenied):
            services.change_role(self.team, self.responder, self.membership(self.admin), Role.RESPONDER)
        with self.assertRaises(services.TeamPermissionDenied):
            services.remove_member(self.team, self.responder, self.membership(self.admin))

    def test_only_owners_grant_or_remove_ownership(self):
        with self.assertRaises(services.TeamPermissionDenied):
            services.add_member(self.team, self.admin, make_user(), Role.OWNER)
        with self.assertRaises(services.TeamPermissionDenied):
            services.change_role(self.team, self.admin, self.membership(self.responder), Role.OWNER)
        with self.assertRaises(services.TeamPermissionDenied):
            services.remove_member(self.team, self.admin, self.membership(self.owner))

        services.change_role(self.team, self.owner, self.membership(self.responder), Role.OWNER)
        self.assertEqual(services.role_for(self.team, self.responder), Role.OWNER)

    def test_the_last_owner_cannot_be_demoted_or_leave(self):
        with self.assertRaisesMessage(services.TeamError, 'at least one owner'):
            services.change_role(self.team, self.owner, self.membership(self.owner), Role.ADMIN)
        with self.assertRaisesMessage(services.TeamError, 'at least one owner'):
            services.remove_member(self.team, self.owner, self.membership(self.owner))

        services.change_role(self.team, self.owner, self.membership(self.admin), Role.OWNER)
        services.remove_member(self.team, self.owner, self.membership(self.owner))
        self.assertFalse(services.is_member(self.team, self.owner))

    def test_members_can_leave_and_admins_remove_responders(self):
        services.remove_member(self.team, self.responder, self.membership(self.responder))
        self.assertFalse(services.is_member(self.team, self.responder))

        other = add_member(self.team)
        services.remove_member(self.team, self.admin, self.membership(other))
        self.assertFalse(services.is_member(self.team, other))


class TeamViewTests(TestCase):
    def setUp(self):
        self.team = make_team('Platform')
        self.owner = owner_of(self.team)
        self.responder = add_member(self.team, make_user('linus'))

    def test_team_pages_are_404_for_outsiders(self):
        self.client.force_login(make_user('outsider'))

        self.assertEqual(self.client.get(reverse('teams:detail', args=[self.team.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse('services:list', args=[self.team.slug])).status_code, 404)

    def test_members_see_the_team_and_their_teams_list(self):
        self.client.force_login(self.responder)

        detail = self.client.get(reverse('teams:detail', args=[self.team.slug]))
        teams = self.client.get(reverse('teams:list'))

        self.assertContains(detail, '@linus')
        self.assertContains(detail, 'Your role: Responder')
        self.assertNotContains(detail, 'Add a member')
        self.assertContains(teams, 'Platform')

    def test_create_team_view(self):
        self.client.force_login(self.responder)

        response = self.client.post(reverse('teams:create'), {'name': 'Data'})

        team = Team.objects.get(name='Data')
        self.assertRedirects(response, team.get_absolute_url())
        self.assertEqual(services.role_for(team, self.responder), Role.OWNER)

    def test_owner_adds_members_by_username_or_email(self):
        make_user('grace', email='grace@example.com')
        make_user('margaret', email='margaret@example.com')
        self.client.force_login(self.owner)
        url = reverse('teams:member_add', args=[self.team.slug])

        self.client.post(url, {'identifier': 'grace', 'role': 'admin'})
        self.client.post(url, {'identifier': 'MARGARET@example.com', 'role': 'responder'})
        unknown = self.client.post(url, {'identifier': 'nobody', 'role': 'responder'}, follow=True)

        roles = dict(Membership.objects.filter(team=self.team).values_list('user__username', 'role'))
        self.assertEqual((roles['grace'], roles['margaret']), ('admin', 'responder'))
        self.assertContains(unknown, 'No Beacon account has that username or email')

    def test_responders_get_403_when_adding_members(self):
        self.client.force_login(self.responder)

        response = self.client.post(reverse('teams:member_add', args=[self.team.slug]),
                                    {'identifier': self.owner.username, 'role': 'responder'})

        self.assertEqual(response.status_code, 403)

    def test_change_role_and_remove_views(self):
        self.client.force_login(self.owner)
        membership = Membership.objects.get(team=self.team, user=self.responder)

        self.client.post(reverse('teams:member_role', args=[self.team.slug, membership.pk]), {'role': 'admin'})
        self.assertEqual(services.role_for(self.team, self.responder), Role.ADMIN)

        self.client.post(reverse('teams:member_remove', args=[self.team.slug, membership.pk]))
        self.assertFalse(services.is_member(self.team, self.responder))

    def test_last_owner_leaving_shows_an_error(self):
        self.client.force_login(self.owner)
        membership = Membership.objects.get(team=self.team, user=self.owner)

        response = self.client.post(reverse('teams:member_remove', args=[self.team.slug, membership.pk]), follow=True)

        self.assertContains(response, 'A team needs at least one owner')
        self.assertTrue(services.is_member(self.team, self.owner))
