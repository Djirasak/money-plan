"""Rendering and delivering one e-mail.

Internal to the mailer: application code never calls ``deliver`` directly. It queues
mail with ``money_plan.mailer.api.queue_email`` and the Celery worker runs ``deliver``
(see ``tasks.py``), so a slow or failing provider never blocks a web request.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.html import strip_tags

TEMPLATE_DIR = "emails"


def render(
    template: str,
    context: dict | None = None,
    language: str | None = None,
) -> tuple[str, str]:
    """Return ``(html, text)`` for ``emails/<template>.html`` (+ optional ``.txt``)."""
    with translation.override(language or settings.LANGUAGE_CODE):
        html = render_to_string(f"{TEMPLATE_DIR}/{template}.html", context or {})
        try:
            text = render_to_string(f"{TEMPLATE_DIR}/{template}.txt", context or {})
        except TemplateDoesNotExist:
            text = strip_tags(html)
    return html, text


def deliver(
    *,
    to: list[str],
    subject: str,
    template: str,
    context: dict | None = None,
    language: str | None = None,
    reply_to: list[str] | None = None,
    tags: list[str] | None = None,
    log=None,
) -> str | None:
    """Send one rendered message (stored on ``log`` when given). Returns the provider's message id."""
    html, text = render(template, context, language)
    if log is not None:  # keep what is actually sent, even if the provider then fails
        log.body_html, log.body_text = html, text
        log.save(update_fields=["body_html", "body_text", "updated_at"])
    message = EmailMultiAlternatives(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        reply_to=reply_to or None,
    )
    message.attach_alternative(html, "text/html")
    if tags:
        message.tags = tags  # Anymail: shows up in the Resend dashboard
    message.send(fail_silently=False)
    status = getattr(message, "anymail_status", None)
    return getattr(status, "message_id", None) if status else None
