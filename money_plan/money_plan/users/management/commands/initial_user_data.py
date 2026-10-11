"""Create the initial superuser and its starter planner data (idempotent).

Settings come from the environment (see ``.envs/.local/.django``):

    INITIAL_USER_USERNAME, INITIAL_USER_EMAIL, INITIAL_USER_PASSWORD

When no password is given a random one is generated and printed once.
An existing user is left untouched unless ``--reset-password`` is passed.
With ``--first-run`` nothing happens once any user exists (used at startup).
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils.crypto import get_random_string

from money_plan.planner.services import ensure_defaults


class Command(BaseCommand):
    help = "Create the initial superuser and its starter planner data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=os.environ.get("INITIAL_USER_USERNAME"),
        )
        parser.add_argument("--email", default=os.environ.get("INITIAL_USER_EMAIL", ""))
        parser.add_argument(
            "--password",
            default=os.environ.get("INITIAL_USER_PASSWORD"),
        )
        parser.add_argument(
            "--first-run",
            action="store_true",
            help="Do nothing if any user already exists.",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Set the password even if the user already exists.",
        )

    def handle(self, *args, **options):
        # people sign in with their email now; the username is only an internal handle
        username = options["username"] or options["email"]
        if not username:
            msg = "Set INITIAL_USER_EMAIL (or pass --email)."
            raise CommandError(msg)

        user_model = get_user_model()
        if options["first_run"] and user_model.objects.exists():
            return
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "email": options["email"],
                "is_staff": True,
                "is_superuser": True,
            },
        )
        generated = None
        if created or options["reset_password"]:
            password = options["password"]
            if not password:
                password = generated = get_random_string(16)
            user.set_password(password)
            user.save(update_fields=["password"])

        ensure_defaults(user)

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created superuser '{username}'."))
        else:
            self.stdout.write(f"User '{username}' already exists.")
        if generated:
            self.stdout.write(self.style.WARNING(f"Generated password: {generated}"))
