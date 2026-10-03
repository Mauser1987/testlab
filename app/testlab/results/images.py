"""Result pictures (M2B): store the original unchanged, derive a display copy.

Storage (server file store, next to the run's DCS data):

    projects/<project_no>/runs/<run_no>/result/images/<upload time>-<file name>              the upload, byte for byte
    projects/<project_no>/runs/<run_no>/result/images/<upload time>-<file name>.preview.jpg  derived display copy

The original is never re-encoded (SHA-256 stored) and is what "open
original" serves. The preview is a JPEG of at most PREVIEW_MAX_PX on the
long side, turned upright from the camera's EXIF orientation, so phone and
microscope pictures display quickly; it is rebuilt from the original when
missing. No image analysis.
"""

import hashlib
import io
import re

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import ResultImage

PREVIEW_MAX_PX = 1600


class ImageUploadError(Exception):
    """The upload is not a usable picture; the message says why."""


def _safe_name(name):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "image")[:120]


def image_dir(test_run):
    return f"projects/{test_run.project.project_no}/runs/{test_run.display_no}/result/images"


def _storage():
    return ResultImage._meta.get_field("file").storage


def _preview_bytes(content):
    with Image.open(io.BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            rgba = image.convert("RGBA")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
    return out.getvalue()


def _inspect(content, name):
    max_bytes = settings.TESTLAB_RESULT_IMAGE_MAX_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise ImageUploadError(f"{name} is larger than {settings.TESTLAB_RESULT_IMAGE_MAX_MB} MB.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            upright = ImageOps.exif_transpose(image)
            return upright.size, image.format or ""
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise ImageUploadError(f"{name} is not a picture TestLab can read.") from error


def next_order(result, category, component):
    highest = result.images.filter(category=category, component=component).aggregate(m=Max("order"))["m"]
    return 0 if highest is None else highest + 1


def add_image(result, uploaded, user, category, component=None, caption=""):
    """Store one uploaded picture unchanged plus its preview; returns the ResultImage."""
    content = uploaded.read()
    original_name = uploaded.name
    (width, height), image_format = _inspect(content, original_name)
    storage = _storage()
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    name = f"{image_dir(result.test_run)}/{stamp}-{_safe_name(original_name)}"
    written = []
    try:
        with transaction.atomic():
            file_name = storage.save(name, ContentFile(content))
            written.append(file_name)
            preview_name = storage.save(f"{file_name}.preview.jpg", ContentFile(_preview_bytes(content)))
            written.append(preview_name)
            return ResultImage.objects.create(
                result=result,
                category=category,
                component=component,
                caption=caption.strip(),
                order=next_order(result, category, component),
                file=file_name,
                original_name=original_name,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                width=width,
                height=height,
                image_format=image_format,
                preview_file=preview_name,
                uploaded_by=user,
            )
    except Exception:
        for written_name in written:
            storage.delete(written_name)
        raise


def preview_name(image):
    """The display copy, rebuilt from the original when it is missing."""
    storage = _storage()
    if image.preview_file and storage.exists(image.preview_file):
        return image.preview_file
    with image.file.open("rb") as original:
        content = original.read()
    name = storage.save(f"{image.file.name}.preview.jpg", ContentFile(_preview_bytes(content)))
    ResultImage.objects.filter(pk=image.pk).update(preview_file=name)
    image.preview_file = name
    return name


def move(image, step):
    """Swap the picture with its neighbour (step -1: earlier, +1: later) within its group."""
    siblings = list(
        image.result.images.filter(category=image.category, component=image.component).order_by("order", "pk")
    )
    index = next(i for i, sibling in enumerate(siblings) if sibling.pk == image.pk)
    target = index + step
    if not 0 <= target < len(siblings):
        return
    siblings[index], siblings[target] = siblings[target], siblings[index]
    with transaction.atomic():
        for order, sibling in enumerate(siblings):
            if sibling.order != order:
                ResultImage.objects.filter(pk=sibling.pk).update(order=order)


def delete_image(image):
    """Remove a picture of a draft Result: the record, the original and its preview."""
    storage = _storage()
    names = [image.file.name, image.preview_file]
    with transaction.atomic():
        image.delete()
        transaction.on_commit(lambda: [storage.delete(n) for n in names if n and storage.exists(n)])


def picture_groups(result, components):
    """Pictures arranged for display: cross sections, Pre ↔ Post per component (None: whole seal), other."""
    pictures = list(result.images.all())
    by = lambda category, component=None: [  # noqa: E731
        p for p in pictures if p.category == category and p.component_id == (component.pk if component else None)
    ]
    comparisons = []
    for component in [None, *components]:
        pre, post = by(ResultImage.Category.PRE_TEST, component), by(ResultImage.Category.POST_TEST, component)
        if pre or post:
            comparisons.append({"component": component, "pre": pre, "post": post})
    return {
        "cross_sections": [p for p in pictures if p.category == ResultImage.Category.CROSS_SECTION],
        "comparisons": comparisons,
        "other": [p for p in pictures if p.category == ResultImage.Category.OTHER],
        "count": len(pictures),
    }
