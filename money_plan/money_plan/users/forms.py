from io import BytesIO

from allauth.account.forms import SignupForm
from allauth.account.models import EmailAddress
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django import forms
from django.contrib.auth import forms as admin_forms
from django.contrib.auth.forms import PasswordChangeForm
from django.utils.translation import gettext_lazy as _
from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError

from money_plan.utils import ImageError
from money_plan.utils import compress_image

from .models import User


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):
        model = User


class UserAdminCreationForm(admin_forms.AdminUserCreationForm):
    """
    Form for User Creation in the Admin Area.
    To change user signup, see UserSignupForm and UserSocialSignupForm.
    """

    class Meta(admin_forms.UserCreationForm.Meta):
        model = User
        error_messages = {
            "username": {"unique": _("This username has already been taken.")},
        }


class UserSignupForm(SignupForm):
    """
    Form that will be rendered on a user sign up section/screen.
    Default fields will be added automatically.
    Check UserSocialSignupForm for accounts created from social.
    """


class UserSocialSignupForm(SocialSignupForm):
    """
    Renders the form when user has signed up using social accounts.
    Default fields will be added automatically.
    See UserSignupForm otherwise.
    """


INPUT = {"class": "input"}


class UsernameChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]
        labels = {"username": _("Username")}
        widgets = {
            "username": forms.TextInput(attrs=INPUT | {"autocomplete": "username"}),
        }
        help_texts = {"username": ""}

    def clean_username(self):
        username = self.cleaned_data["username"]
        taken = User.objects.filter(username__iexact=username).exclude(
            pk=self.instance.pk,
        )
        if taken.exists():
            msg = _("This username has already been taken.")
            raise forms.ValidationError(msg)
        return username


class EmailChangeForm(forms.Form):
    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs=INPUT | {"autocomplete": "email"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        taken_user = User.objects.filter(email__iexact=email).exclude(pk=self.user.pk)
        taken_addr = EmailAddress.objects.filter(email__iexact=email).exclude(
            user=self.user,
        )
        if taken_user.exists() or taken_addr.exists():
            msg = _("This email is already used by another account.")
            raise forms.ValidationError(msg)
        return email

    def save(self) -> User:
        """Store the address on the user and keep allauth's address table in step.

        The new address starts unverified; the view sends the confirmation mail."""
        email = self.cleaned_data["email"]
        self.user.email = email
        self.user.save(update_fields=["email"])
        EmailAddress.objects.filter(user=self.user).delete()
        EmailAddress.objects.create(
            user=self.user,
            email=email,
            primary=True,
            verified=False,
        )
        return self.user


class AccountPasswordChangeForm(PasswordChangeForm):
    """Django's password change, with the app's input styling and no wall-of-text help."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(INPUT)
            field.help_text = ""
        self.fields["old_password"].label = _("Current password")
        self.fields["new_password1"].label = _("New password")
        self.fields["new_password2"].label = _("Confirm new password")
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"


class NameChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]
        labels = {"first_name": _("First name"), "last_name": _("Last name")}
        widgets = {
            "first_name": forms.TextInput(attrs=INPUT | {"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs=INPUT | {"autocomplete": "family-name"}),
        }

    def save(self, commit=True):  # noqa: FBT002
        user = self.instance
        user.save_name(self.cleaned_data["first_name"], self.cleaned_data["last_name"])
        return user


MAX_PHOTO_UPLOAD = 10_000_000  # 10 MB before compression
PHOTO_SIDE = 512  # px, square
PHOTO_MAX_BYTES = 200_000


class PhotoChangeForm(forms.Form):
    photo = forms.FileField(
        label=_("Profile photo"),
        widget=forms.ClearableFileInput(
            attrs=INPUT | {"accept": "image/*", "data-photo-input": ""},
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_photo(self):
        upload = self.cleaned_data["photo"]
        if upload.size > MAX_PHOTO_UPLOAD:
            raise forms.ValidationError(_("The photo must be 10 MB or smaller."))
        try:
            squared = _square(upload.read())
            return compress_image(
                squared,
                max_bytes=PHOTO_MAX_BYTES,
                max_side=PHOTO_SIDE,
            ).as_content_file("photo")
        except ImageError as exc:
            raise forms.ValidationError(_("Choose a valid image file.")) from exc

    def save(self):
        user = self.user
        old = user.photo.name
        user.photo.save(self.cleaned_data["photo"].name, self.cleaned_data["photo"])
        if old and old != user.photo.name:
            user.photo.storage.delete(old)
        return user


def _square(data: bytes) -> bytes:
    """Centre-crop to a square (after EXIF rotation) so the circle never shows bars."""
    try:
        with Image.open(BytesIO(data)) as opened:
            img = ImageOps.exif_transpose(opened)
            img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        msg = "Not a valid image"
        raise ImageError(msg) from exc
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    out = BytesIO()
    img.crop((left, top, left + side, top + side)).save(out, "PNG")
    return out.getvalue()
