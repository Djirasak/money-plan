from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.db.models import ImageField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def photo_path(instance: User, filename: str) -> str:
    """avatars/<user id>/<random>.<ext>: never reuses a name, so no stale caches."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"avatars/{instance.pk}/{uuid.uuid4().hex}.{ext}"


class User(AbstractUser):
    """
    Default custom user model for Money Plan.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    # ``first_name`` / ``last_name`` come from AbstractUser; ``name`` keeps the combined
    # display name that the admin and API already read.

    photo = ImageField(_("Profile photo"), upload_to=photo_path, blank=True)

    @property
    def photo_url(self) -> str:
        """Django streams the file (the bucket is private); the name changes on every upload."""
        if not self.photo:
            return ""
        return f"{reverse('users:photo')}?v={uuid.uuid5(uuid.NAMESPACE_URL, self.photo.name).hex[:8]}"

    def save_name(self, first_name: str, last_name: str) -> None:
        """Store the two parts and keep the combined display name in step."""
        self.first_name = first_name.strip()
        self.last_name = last_name.strip()
        self.name = f"{self.first_name} {self.last_name}".strip()
        self.save(update_fields=["first_name", "last_name", "name"])

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})
