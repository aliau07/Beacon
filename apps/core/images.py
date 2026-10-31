"""Image uploads (avatars, postmortem screenshots). Every image is decoded and re-encoded, which strips EXIF data
such as GPS location and camera details; the EXIF orientation is applied first so the picture stays upright."""
from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class ImageError(Exception):
    """An upload that is not a usable image."""


def _has_alpha(image):
    return image.mode in ('RGBA', 'LA', 'PA') or (image.mode == 'P' and 'transparency' in image.info)


def process_image(uploaded_file, max_size, crop=False):
    """Return a ContentFile holding the upload shrunk to fit `max_size` (or cropped to fill it exactly).

    JPEGs stay JPEG; other formats become PNG so screenshots keep sharp text and transparency.
    """
    uploaded_file.seek(0)
    try:
        with Image.open(uploaded_file) as original:
            source_format = original.format
            if source_format not in ALLOWED_FORMATS:
                raise ImageError('Upload a JPEG, PNG, WebP or GIF image.')
            original.load()
            image = ImageOps.exif_transpose(original)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ImageError('Upload a valid image file.') from error

    if crop:
        image = ImageOps.fit(image, max_size, Image.Resampling.LANCZOS)
    else:
        image.thumbnail(max_size, Image.Resampling.LANCZOS)

    buffer = BytesIO()
    if source_format == 'JPEG':
        clean = image.convert('RGB')
        clean.info = {}
        clean.save(buffer, format='JPEG', quality=85, optimize=True)
        extension = 'jpg'
    else:
        clean = image.convert('RGBA' if _has_alpha(image) else 'RGB')
        clean.info = {}
        clean.save(buffer, format='PNG', optimize=True)
        extension = 'png'
    return ContentFile(buffer.getvalue(), name=f'{uuid4().hex}.{extension}')
