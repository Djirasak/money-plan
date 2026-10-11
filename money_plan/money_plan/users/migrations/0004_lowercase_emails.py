from django.db import migrations


def lowercase_emails(apps, schema_editor):
    """allauth finds an email login by its lower-cased value: store emails that way.

    A row is left alone when lower-casing it would collide with another (never happens
    in a one-person app, but a migration must not crash on it)."""
    User = apps.get_model("users", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")
    taken_users = set(User.objects.exclude(email="").values_list("email", flat=True))
    for user in User.objects.exclude(email=""):
        lowered = user.email.strip().lower()
        if lowered != user.email and lowered not in taken_users:
            taken_users.discard(user.email)
            taken_users.add(lowered)
            User.objects.filter(pk=user.pk).update(email=lowered)
    taken = set(EmailAddress.objects.values_list("email", flat=True))
    for address in EmailAddress.objects.all():
        lowered = address.email.strip().lower()
        if lowered != address.email and lowered not in taken:
            taken.discard(address.email)
            taken.add(lowered)
            EmailAddress.objects.filter(pk=address.pk).update(email=lowered)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_user_photo"),
        ("account", "0001_initial"),
    ]

    operations = [migrations.RunPython(lowercase_emails, migrations.RunPython.noop)]
