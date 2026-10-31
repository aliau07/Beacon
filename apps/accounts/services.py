"""The accounts app's public interface: finding people and keeping their avatar tidy."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.core.images import process_image

AVATAR_SIZE = (256, 256)


def find_user(identifier):
    """The active user whose username or email address matches `identifier` (case-insensitive), or None."""
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    matches = get_user_model().objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier), is_active=True)
    return matches.first()


def set_avatar(user, uploaded_file):
    """Store a square, metadata-free copy of the upload as the avatar, replacing any old one. Raises ImageError."""
    content = process_image(uploaded_file, AVATAR_SIZE, crop=True)
    old_name = user.avatar.name
    user.avatar.save(content.name, content, save=False)
    user.save(update_fields=['avatar'])
    if old_name:
        user.avatar.storage.delete(old_name)


def remove_avatar(user):
    if user.avatar:
        user.avatar.delete(save=False)
        user.save(update_fields=['avatar'])
