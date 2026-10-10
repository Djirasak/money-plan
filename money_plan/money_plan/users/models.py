from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


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
