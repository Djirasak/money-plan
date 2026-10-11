from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class EmailLog(models.Model):
    """One queued e-mail and what became of it, including the body that was actually sent."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")  # the provider accepted it
        DELAYED = "delayed", _("Delayed")
        DELIVERED = "delivered", _("Delivered")
        BOUNCED = "bounced", _("Bounced")
        COMPLAINED = "complained", _("Complained")
        FAILED = "failed", _("Failed")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="email_logs",
    )
    to = models.CharField(_("To"), max_length=1000)
    template = models.CharField(_("Template"), max_length=100)
    subject = models.CharField(_("Subject"), max_length=255)
    status = models.CharField(
        _("Status"),
        max_length=12,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    message_id = models.CharField(
        _("Provider message id"),
        max_length=100,
        blank=True,
        db_index=True,
    )
    body_html = models.TextField(_("HTML body"), blank=True)
    body_text = models.TextField(_("Text body"), blank=True)
    attempts = models.PositiveSmallIntegerField(_("Attempts"), default=0)
    error = models.CharField(_("Last error"), max_length=500, blank=True)
    # e.g. "monthly_report:2026-10:42": a second queue_email with the same key is skipped
    dedupe_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.template} -> {self.to} ({self.status})"

    # A later "worse" or "further" status wins; a late "delivered" never hides a bounce.
    _RANK = {
        Status.QUEUED: 0,
        Status.SENT: 1,
        Status.DELAYED: 2,
        Status.DELIVERED: 3,
        Status.FAILED: 4,
        Status.BOUNCED: 5,
        Status.COMPLAINED: 6,
    }

    def advance(self, status: str, **fields) -> None:
        """Move to ``status`` unless the log already is somewhere further along."""
        if self._RANK[self.Status(status)] >= self._RANK[self.Status(self.status)]:
            self.status = status
        for name, value in fields.items():
            setattr(self, name, value)
        self.save()
