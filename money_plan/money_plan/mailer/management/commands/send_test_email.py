"""Queue the test message, to check the provider and the worker end to end."""

from django.core.management.base import BaseCommand

from money_plan.mailer.api import queue_email


class Command(BaseCommand):
    help = "Queue a test e-mail for the Celery worker."

    def add_arguments(self, parser):
        parser.add_argument("to", help="Recipient address")
        parser.add_argument("--language", default=None, help="th or en")
        parser.add_argument("--sender", default=None, help="account, report, ...")

    def handle(self, *args, to, language, sender, **options):
        queue_email(
            to=to,
            subject="Test email",
            template="test",
            language=language,
            sender=sender,
            tags=["test"],
        )
        self.stdout.write(f"Queued a test email to {to}. Watch the celeryworker log.")
