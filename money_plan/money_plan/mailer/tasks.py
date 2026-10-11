from __future__ import annotations

import logging

import requests
from anymail.exceptions import AnymailAPIError
from anymail.exceptions import AnymailRequestsAPIError
from celery import shared_task

from . import services

logger = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429}  # plus every 5xx
MAX_RETRIES = 5


def _worth_retrying(exc: Exception) -> bool:
    """Network trouble, rate limits and provider 5xx pass on their own; a 4xx
    (bad address, unverified domain, bad key) would fail again, so it does not retry."""
    if isinstance(exc, AnymailRequestsAPIError) and exc.response is not None:
        status = exc.response.status_code
        return status in RETRY_STATUS or status >= 500  # noqa: PLR2004
    # requests raises connection errors and timeouts as-is, without an HTTP answer
    return isinstance(exc, requests.RequestException)


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
) -> str | None:
    """The one way mail leaves the app. Queue it with ``queue_email``."""
    try:
        message_id = services.deliver(
            to=to,
            subject=subject,
            template=template,
            context=context,
            language=language,
            reply_to=reply_to,
            tags=tags,
        )
    except (AnymailAPIError, requests.RequestException) as exc:
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
            raise self.retry(exc=exc, countdown=delay) from exc
        logger.exception(
            "Mail '%s' to %d recipient(s) failed for good",
            template,
            len(to),
        )
        raise
    logger.info(
        "Mail '%s' sent to %d recipient(s) (id=%s)",
        template,
        len(to),
        message_id,
    )
    return message_id
