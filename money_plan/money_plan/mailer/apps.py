from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MailerConfig(AppConfig):
    name = "money_plan.mailer"
    verbose_name = _("Mailer")

    def ready(self):
        from . import signals  # noqa: F401, PLC0415 - connects the webhook receiver
