from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.core.tests.factories import TemporaryMediaMixin, image_upload, make_user

from . import services

User = get_user_model()
PASSWORD = 'correct-horse-battery-staple'
FAST_HASHER = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_HASHER
class SignupTests(TestCase):
    def signup(self, url=None, **overrides):
        data = {'username': 'aoife', 'email': 'aoife@example.com', 'time_zone': 'Europe/Dublin',
                'password1': PASSWORD, 'password2': PASSWORD, **overrides}
        return self.client.post(url or reverse('accounts:signup'), data)

    def test_signup_creates_and_logs_in_the_user_with_a_time_zone(self):
        response = self.signup()

        self.assertRedirects(response, reverse('teams:list'))
        user = User.objects.get(username='aoife')
        self.assertEqual(user.time_zone, 'Europe/Dublin')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_weak_passwords_and_unknown_time_zones_are_rejected(self):
        weak = self.signup(password1='password', password2='password')
        bad_zone = self.signup(time_zone='Mars/Olympus_Mons')

        self.assertTrue(weak.context['form'].has_error('password2'))
        self.assertTrue(bad_zone.context['form'].has_error('time_zone'))
        self.assertFalse(User.objects.exists())

    def test_email_is_required_and_unique(self):
        User.objects.create_user('existing', email='Aoife@example.com')

        self.assertTrue(self.signup(email='').context['form'].has_error('email'))
        self.assertContains(self.signup(email='aoife@EXAMPLE.com'), 'An account with this email address already exists.')

    def test_next_url_is_followed_only_when_safe(self):
        safe = self.signup(url=f"{reverse('accounts:signup')}?next=/incidents/")
        self.client.logout()
        unsafe = self.signup(url=f"{reverse('accounts:signup')}?next=https://evil.example.com/", username='b', email='b@example.com')

        self.assertRedirects(safe, '/incidents/', fetch_redirect_response=False)
        self.assertRedirects(unsafe, reverse('teams:list'))


@FAST_HASHER
class LoginProfileTests(TemporaryMediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('aoife', email='aoife@example.com', password=PASSWORD)

    def update_profile(self, **overrides):
        data = {'first_name': 'Aoife', 'last_name': 'Byrne', 'email': 'ab@example.com', 'time_zone': 'America/New_York'}
        data.update(overrides)
        return self.client.post(reverse('accounts:profile'), data)

    def test_login_and_logout(self):
        response = self.client.post(reverse('accounts:login'), {'username': 'aoife', 'password': PASSWORD})
        self.assertRedirects(response, '/', fetch_redirect_response=False)

        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.client.post(reverse('accounts:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_update_profile_and_password(self):
        self.client.force_login(self.user)

        self.update_profile()
        new_password = 'another-long-passphrase-42'
        self.client.post(reverse('accounts:password_change'), {
            'old_password': PASSWORD, 'new_password1': new_password, 'new_password2': new_password,
        })

        self.user.refresh_from_db()
        self.assertEqual((self.user.get_full_name(), self.user.email), ('Aoife Byrne', 'ab@example.com'))
        self.assertEqual(self.user.time_zone, 'America/New_York')
        self.assertTrue(self.user.check_password(new_password))

    def test_avatar_is_cropped_square_and_stripped_of_exif(self):
        self.client.force_login(self.user)
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'
        upload = image_upload('me.jpg', size=(800, 400), exif=exif)

        self.update_profile(new_avatar=upload)

        self.user.refresh_from_db()
        with Image.open(self.user.avatar.path) as avatar:
            self.assertEqual(avatar.size, services.AVATAR_SIZE)
            self.assertEqual(len(avatar.getexif()), 0)
        self.assertContains(self.client.get(reverse('accounts:profile')), self.user.avatar.url)

    def test_avatar_can_be_removed_and_non_images_are_rejected(self):
        self.client.force_login(self.user)
        self.update_profile(new_avatar=image_upload('me.png', image_format='PNG'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar)

        not_an_image = BytesIO(b'GIF89a-not-really')
        not_an_image.name = 'fake.gif'
        rejected = self.update_profile(new_avatar=not_an_image)
        self.assertTrue(rejected.context['form'].has_error('new_avatar'))

        self.update_profile(remove_avatar='on')
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)


class FindUserTests(TestCase):
    def test_find_by_username_or_email_ignoring_case(self):
        user = make_user('grace', email='grace@example.com')
        make_user('inactive', is_active=False)

        self.assertEqual(services.find_user('GRACE'), user)
        self.assertEqual(services.find_user(' Grace@Example.com '), user)
        self.assertIsNone(services.find_user('inactive'))
        self.assertIsNone(services.find_user(''))

    def test_admin_user_pages_show_beacon_fields(self):
        admin = make_user('root', is_staff=True, is_superuser=True)
        self.client.force_login(admin)

        response = self.client.get(reverse('admin:accounts_user_change', args=[admin.pk]))

        self.assertContains(response, 'time_zone')
