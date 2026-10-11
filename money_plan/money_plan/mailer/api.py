"""The only entry point other apps use to send mail."""

from __future__ import annotations

import json

from django.db import IntegrityError
from django.db import transaction

from .models import EmailLog
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
    user=None,
    dedupe_key: str | None = None,
) -> EmailLog | None:
    """Queue one e-mail for the Celery worker; returns immediately with its log row.

    ``template`` names ``templates/emails/<template>.html`` (and an optional ``.txt``).
    ``context`` must be JSON-serialisable (ids, strings, numbers): pass what the
    template needs, not model instances. The task is sent after the current database
    transaction commits, so a rolled-back change never mails anyone.

    ``dedupe_key`` makes the call idempotent: when a mail with the same key is already
    queued or sent, nothing is queued and ``None`` is returned (a failed one is retried).
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

    log = _new_log(
        user=user,
        to=", ".join(recipients),
        template=template,
        subject=subject,
        dedupe_key=dedupe_key,
    )
    if log is None:
        return None
    kwargs = {
        "to": recipients,
        "subject": subject,
        "template": template,
        "context": context,
        "language": language,
        "reply_to": reply,
        "tags": tags,
        "log_id": log.pk,
    }
    transaction.on_commit(lambda: send_email.delay(**kwargs))
    return log


def _new_log(*, dedupe_key: str | None, **fields) -> EmailLog | None:
    if not dedupe_key:
        return EmailLog.objects.create(**fields)
    try:
        with transaction.atomic():
            return EmailLog.objects.create(dedupe_key=dedupe_key, **fields)
    except IntegrityError:
        pass
    # Same key already used: only a mail that failed for good is queued again.
    updated = EmailLog.objects.filter(
        dedupe_key=dedupe_key,
        status=EmailLog.Status.FAILED,
    ).update(status=EmailLog.Status.QUEUED, error="", attempts=0, **fields)
    return EmailLog.objects.get(dedupe_key=dedupe_key) if updated else None
