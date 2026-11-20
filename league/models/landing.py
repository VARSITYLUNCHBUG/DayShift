"""The landing page's call to action, edited by staff in the admin: a tagline, and a message of
the day or advert (an image, some HTML, or a video). The page shows the first live one of each,
by `order`; with none, it shows its own words (services/web/src/screens/signin/SignIn.tsx)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePath
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from league.domain import images, youtube


class LandingKind(models.TextChoices):
    TAGLINE = "tagline", "Tagline"
    IMAGE = "image", "Message of the day / advert: an image"
    HTML = "html", "Message of the day / advert: HTML"
    VIDEO = "video", "Message of the day / advert: a video"


def _upload_to(item: LandingItem, filename: str) -> str:
    """A random name: the edge serves these for a year, so a replaced file needs a new one."""
    return f"landing/{uuid4().hex}{PurePath(filename).suffix.lower()}"


class LandingItem(models.Model):
    kind = models.CharField(max_length=8, choices=LandingKind.choices)
    name = models.CharField(max_length=100, help_text="For staff only: what this is.")
    text = models.TextField(
        blank=True,
        help_text=(
            "A tagline: Markdown, such as **bold**, *italic* and [a link](https://example.com). "
            "Its first paragraph is the page's headline, in its biggest type (a line break starts "
            "a new line); any after a blank line go under it. "
            "HTML: the HTML itself. Scripts, styles and frames are taken out, and images in it "
            "must be on this site."
        ),
    )
    image = models.FileField(
        upload_to=_upload_to, blank=True, help_text="PNG, JPEG, WebP or GIF, up to 5 MB."
    )
    video = models.FileField(
        upload_to=_upload_to,
        blank=True,
        help_text="MP4 or WebM, up to 20 MB. It plays muted and loops. Or use a YouTube link.",
    )
    youtube_url = models.URLField(blank=True, help_text="A YouTube link, instead of a file.")
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="What the image or video shows, for people who can't see it.",
    )
    link_url = models.URLField(blank=True, help_text="Optional: where pressing the advert goes.")
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True, help_text="Empty: from now.")
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Empty: until turned off.")
    order = models.PositiveSmallIntegerField(default=0, help_text="Lowest shows first.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "landing_items"
        ordering = ("order", "-updated_at")

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.kind in {LandingKind.TAGLINE, LandingKind.HTML} and not self.text.strip():
            errors["text"] = "Write the text this shows."
        if self.kind == LandingKind.IMAGE:
            if not self.image:
                errors["image"] = "Upload the image."
            elif problem := _problem(self.image, "image"):
                errors["image"] = problem
        if self.kind == LandingKind.VIDEO:
            if bool(self.video) == bool(self.youtube_url):
                errors["video"] = "Upload a video or give a YouTube link: one of the two."
            elif self.video:
                if problem := _problem(self.video, "video"):
                    errors["video"] = problem
            elif youtube.video_id(self.youtube_url) is None:
                errors["youtube_url"] = "That isn't a YouTube video link."
        if self.kind in {LandingKind.IMAGE, LandingKind.VIDEO} and not self.alt_text.strip():
            errors["alt_text"] = "Say what it shows."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "It has to end after it starts."
        if errors:
            raise ValidationError(errors)


_CHECKS: dict[str, tuple[Callable[[bytes], str | None], int, str]] = {
    "image": (images.detect_advert_image, images.MAX_ADVERT_IMAGE_BYTES, "an image"),
    "video": (images.detect_video, images.MAX_ADVERT_VIDEO_BYTES, "a video"),
}


def _problem(field: Any, kind: str) -> str | None:
    """Why an uploaded file can't be used, or None. Its bytes are checked, not its name."""
    detect, limit, what = _CHECKS[kind]
    if field.size > limit:
        return f"That's too big: up to {limit // (1024 * 1024)} MB."
    field.open("rb")
    try:
        head = field.read(16)
    finally:
        field.seek(0)
    return None if detect(head) else f"That isn't {what} we can show."


# An item's files go with it: when it's deleted (one at a time or in bulk), and when a file is
# replaced or cleared. Uploads have random names, so nothing else ever points at them.


@receiver(pre_save, sender=LandingItem)
def _drop_replaced_files(sender: type[LandingItem], instance: LandingItem, **kwargs: Any) -> None:
    if not instance.pk:
        return
    old = LandingItem.objects.filter(pk=instance.pk).values_list("image", "video").first()
    for name, field in zip(old or (), (instance.image, instance.video), strict=False):
        if name and name != field.name:
            field.storage.delete(name)


@receiver(post_delete, sender=LandingItem)
def _drop_files(sender: type[LandingItem], instance: LandingItem, **kwargs: Any) -> None:
    for field in (instance.image, instance.video):
        if field and field.name:
            field.storage.delete(field.name)
