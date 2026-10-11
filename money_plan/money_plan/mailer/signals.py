"""Delivery events from the provider (Resend webhook, handled by django-anymail)."""

from anymail.signals import tracking
from django.dispatch import receiver

from .models import EmailLog

Status = EmailLog.Status

EVENT_STATUS = {
    "sent": Status.SENT,
    "delivered": Status.DELIVERED,
    "deferred": Status.DELAYED,  # Resend: email.delivery_delayed
    "bounced": Status.BOUNCED,
    "rejected": Status.BOUNCED,
    "complained": Status.COMPLAINED,
    "failed": Status.FAILED,
}


@receiver(tracking)
def update_email_log(sender, event, esp_name, **kwargs):
    status = EVENT_STATUS.get(event.event_type)
    if not status or not event.message_id:
        return  # opened/clicked/etc. are not tracked on purpose
    detail = (event.description or event.reject_reason or "")[:500]
    for log in EmailLog.objects.filter(message_id=event.message_id):
        log.advance(
            status,
            **({"error": detail} if detail and status != Status.DELIVERED else {}),
        )
