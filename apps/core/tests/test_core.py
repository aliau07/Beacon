from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.views import View
from PIL import Image

from ..choices import worst_severity
from ..images import ImageError, process_image
from ..middleware import UserTimezoneMiddleware
from ..mixins import StaffRequiredMixin
from ..notifications import notify, render_plain_text
from ..templatetags.core_extras import duration, severity_badge
from ..validators import validate_time_zone
from .factories import image_upload, make_user


class FilterAndChoiceTests(SimpleTestCase):
    def test_severity_badge(self):
        self.assertEqual(severity_badge('critical'), 'text-bg-danger')
        self.assertEqual(severity_badge('info'), 'text-bg-secondary')
        self.assertEqual(severity_badge('bogus'), 'text-bg-secondary')

    def test_duration(self):
        self.assertEqual(duration(timedelta(days=1, hours=2, minutes=5, seconds=30)), '1d 2h 5m')
        self.assertEqual(duration(timedelta(minutes=45)), '45m')
        self.assertEqual(duration(timedelta(seconds=20)), '<1m')
        self.assertEqual(duration(None), '')

    def test_worst_severity(self):
        self.assertEqual(worst_severity(['info', 'critical', 'warning']), 'critical')
        self.assertEqual(worst_severity(['warning', 'error']), 'error')
        self.assertIsNone(worst_severity([]))


class TimeZoneTests(SimpleTestCase):
    def test_validate_time_zone(self):
        validate_time_zone('Europe/Dublin')
        validate_time_zone('UTC')
        with self.assertRaises(ValidationError):
            validate_time_zone('Europe/Atlantis')

    def test_middleware_activates_the_users_time_zone(self):
        seen = []

        def view(request):
            seen.append(timezone.get_current_timezone_name())
            return HttpResponse()

        request = RequestFactory().get('/')
        request.user = type('SignedIn', (), {'is_authenticated': True, 'time_zone': 'Asia/Tokyo'})()
        UserTimezoneMiddleware(view)(request)
        request.user = AnonymousUser()
        UserTimezoneMiddleware(view)(request)

        self.assertEqual(seen, ['Asia/Tokyo', 'UTC'])


class StaffOnlyView(StaffRequiredMixin, View):
    def get(self, request):
        return HttpResponse('ok')


class StaffRequiredMixinTests(TestCase):
    def get(self, user):
        request = RequestFactory().get('/staff-only/')
        request.user = user
        return StaffOnlyView.as_view()(request)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.get(AnonymousUser())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_non_staff_user_is_forbidden(self):
        with self.assertRaises(PermissionDenied):
            self.get(make_user('responder'))

    def test_staff_user_is_allowed(self):
        self.assertEqual(self.get(make_user('staff', is_staff=True)).status_code, 200)


TEST_TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'OPTIONS': {'loaders': [('django.template.loaders.locmem.Loader', {
        'note.txt': 'Hi {{ user.get_username }}: {{ text }} {{ site_url }}/incidents/1/',
    })]},
}]


@override_settings(SITE_URL='https://beacon.example.com/', TEMPLATES=TEST_TEMPLATES)
class NotificationTests(TestCase):
    def test_sends_plain_text_without_html_escaping(self):
        user = make_user("o'brien", email='ob@example.com')

        sent = notify(user, 'Paged', 'note.txt', {'text': "It's <down> & burning"})

        self.assertTrue(sent)
        email = mail.outbox[0]
        self.assertEqual((email.subject, email.to), ('[Beacon] Paged', ['ob@example.com']))
        self.assertEqual(email.body, "Hi o'brien: It's <down> & burning https://beacon.example.com/incidents/1/")

    def test_users_without_email_are_skipped(self):
        user = make_user('noemail', email='')

        self.assertFalse(notify(user, 'Hello', 'note.txt'))
        self.assertEqual(mail.outbox, [])

    def test_render_plain_text(self):
        self.assertEqual(render_plain_text('note.txt', {'text': 'A & B'}), 'Hi : A & B /incidents/1/')


class ImageTests(SimpleTestCase):
    def open(self, content):
        return Image.open(BytesIO(content.read()))

    def test_shrinks_to_fit_keeping_the_aspect_ratio(self):
        result = process_image(image_upload(size=(3200, 1600)), (1600, 1600))

        with self.open(result) as image:
            self.assertEqual((image.format, image.size), ('JPEG', (1600, 800)))
        self.assertTrue(result.name.endswith('.jpg'))

    def test_crop_fills_the_box_exactly(self):
        with self.open(process_image(image_upload(size=(800, 300)), (256, 256), crop=True)) as image:
            self.assertEqual(image.size, (256, 256))

    def test_exif_is_stripped_after_applying_orientation(self):
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'   # camera make
        exif[0x0112] = 6              # orientation: rotate 90 degrees to display
        upload = image_upload(size=(400, 200), exif=exif)

        with self.open(process_image(upload, (1600, 1600))) as image:
            self.assertEqual(image.size, (200, 400))
            self.assertEqual(len(image.getexif()), 0)
            self.assertNotIn('exif', image.info)

    def test_png_with_transparency_stays_png(self):
        upload = image_upload('chart.png', image_format='PNG', mode='RGBA', colour=(0, 0, 0, 0))

        result = process_image(upload, (100, 100))

        with self.open(result) as image:
            self.assertEqual((image.format, image.mode), ('PNG', 'RGBA'))

    def test_rejects_non_images_and_unsupported_formats(self):
        not_an_image = BytesIO(b'definitely not a picture')
        with self.assertRaises(ImageError):
            process_image(not_an_image, (100, 100))
        with self.assertRaisesMessage(ImageError, 'Upload a JPEG, PNG, WebP or GIF image.'):
            process_image(image_upload('old.bmp', image_format='BMP'), (100, 100))


class SiteTests(TestCase):
    def test_health_check(self):
        self.assertEqual(self.client.get(reverse('core:health')).json(), {'status': 'ok'})

    def test_custom_404_page(self):
        response = self.client.get('/no-such-page/')

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')

    def test_home_is_a_landing_page_for_visitors_and_incidents_for_users(self):
        anonymous = self.client.get('/')
        self.client.force_login(make_user('aoife'))
        signed_in = self.client.get('/')

        self.assertContains(anonymous, 'Log in')
        self.assertContains(anonymous, 'Events API')
        self.assertRedirects(signed_in, reverse('incidents:list'))

    def test_navigation_when_logged_in(self):
        self.client.force_login(make_user('aoife', time_zone='Europe/Dublin'))

        response = self.client.get(reverse('incidents:list'))

        for label in ('Incidents', 'On call', 'Teams', 'Inbox', 'Times shown in Europe/Dublin'):
            self.assertContains(response, label)
        self.assertNotContains(response, 'Sign up')
