"""Plain-text notification emails, shared by every app that tells people about activity."""
from django.conf import settings
from django.core.mail import send_mail
from django.template import Context
from django.template.loader import get_template


def render_plain_text(template_name, context):
    """Render a .txt template without HTML escaping (an apostrophe should not become &#x27;)."""
    template = get_template(template_name).template
    return template.render(Context(context, autoescape=False))


def notify(user, subject, template_name, context=None):
    """Email `user` the rendered template. Users without an email address are skipped; returns whether sent."""
    if not user.email:
        return False
    body = render_plain_text(template_name, {'user': user, 'site_url': settings.SITE_URL.rstrip('/'), **(context or {})})
    send_mail(f'[Beacon] {subject}', body, None, [user.email])
    return True
