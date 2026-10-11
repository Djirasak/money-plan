"""The only entry point other apps use to send mail."""

from __future__ import annotations

import json

from django.db import transaction

from .tasks import send_email


def queue_email(
    *,
    to: str | list[str],
    subject: str,
    template: str,
    context: dict | None = None,
    language: str | None = None,
    reply_to: str | list[str] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Queue one e-mail for the Celery worker; returns immediately.

    ``template`` names ``templates/emails/<template>.html`` (and an optional ``.txt``).
    ``context`` must be JSON-serialisable (ids, strings, numbers): pass what the
    template needs, not model instances. The task is sent after the current database
    transaction commits, so a rolled-back change never mails anyone.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        msg = "queue_email needs at least one recipient"
        raise ValueError(msg)
    reply = [reply_to] if isinstance(reply_to, str) else reply_to
    try:
        json.dumps(context or {})
    except TypeError as exc:
        msg = "queue_email context must be JSON-serialisable"
        raise TypeError(msg) from exc
    kwargs = {
        "to": recipients,
        "subject": subject,
        "template": template,
        "context": context,
        "language": language,
        "reply_to": reply,
        "tags": tags,
    }
    transaction.on_commit(lambda: send_email.delay(**kwargs))
