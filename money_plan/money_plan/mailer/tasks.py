from __future__ import annotations

import logging
from datetime import timedelta

import requests
from anymail.exceptions import AnymailAPIError
from anymail.exceptions import AnymailRequestsAPIError
from celery import shared_task
from django.utils import timezone

from . import services
from .models import EmailLog

logger = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429}  # plus every 5xx
MAX_RETRIES = 5
LOG_KEEP_DAYS = 90


def _worth_retrying(exc: Exception) -> bool:
    """Network trouble, rate limits and provider 5xx pass on their own; a 4xx
    (bad address, unverified domain, bad key) would fail again, so it does not retry."""
    if isinstance(exc, AnymailRequestsAPIError) and exc.response is not None:
        status = exc.response.status_code
        return status in RETRY_STATUS or status >= 500  # noqa: PLR2004
    # requests raises connection errors and timeouts as-is, without an HTTP answer
    return isinstance(exc, requests.RequestException)


def _log(log_id: int | None) -> EmailLog | None:
    return EmailLog.objects.filter(pk=log_id).first() if log_id else None


@shared_task(bind=True, name="mailer.send_email", max_retries=MAX_RETRIES)
def send_email(
    self,
    *,
    to: list[str],
    subject: str,
    template: str,
    context: dict | None = None,
    language: str | None = None,
    reply_to: list[str] | None = None,
    tags: list[str] | None = None,
    log_id: int | None = None,
) -> str | None:
    """The one way mail leaves the app. Queue it with ``queue_email``."""
    log = _log(log_id)
    if log:
        log.advance(EmailLog.Status.QUEUED, attempts=self.request.retries + 1)
    try:
        message_id = services.deliver(
            to=to,
            subject=subject,
            template=template,
            context=context,
            language=language,
            reply_to=reply_to,
            tags=tags,
            log=log,
        )
    except (AnymailAPIError, requests.RequestException) as exc:
        error = str(exc)[:500]
        if _worth_retrying(exc) and self.request.retries < MAX_RETRIES:
            delay = min(
                2 ** (self.request.retries + 1) * 30,
                900,
            )  # 1m, 2m, 4m ... max 15m
            logger.warning(
                "Mail '%s' failed (%s); retrying in %ss",
                template,
                exc,
                delay,
            )
            if log:
                log.advance(EmailLog.Status.QUEUED, error=error)
            raise self.retry(exc=exc, countdown=delay) from exc
        logger.exception(
            "Mail '%s' to %d recipient(s) failed for good",
            template,
            len(to),
        )
        if log:
            log.advance(EmailLog.Status.FAILED, error=error)
        raise
    if log:
        log.advance(
            EmailLog.Status.SENT,
            message_id=message_id or "",
            sent_at=timezone.now(),
            error="",
        )
    logger.info(
        "Mail '%s' sent to %d recipient(s) (id=%s)",
        template,
        len(to),
        message_id,
    )
    return message_id


@shared_task(name="mailer.purge_old_logs")
def purge_old_logs(days: int = LOG_KEEP_DAYS) -> int:
    """Addresses are personal data: drop log rows older than ``days`` days."""
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = EmailLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted
