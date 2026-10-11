from __future__ import annotations

from unittest import mock

import pytest
import requests
from anymail.exceptions import AnymailRequestsAPIError
from django.core import mail
from django.core.management import call_command

from money_plan.mailer import services
from money_plan.mailer.api import queue_email
from money_plan.mailer.models import EmailLog
from money_plan.mailer.tasks import purge_old_logs
from money_plan.mailer.tasks import send_email
from money_plan.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def api_error(status: int) -> AnymailRequestsAPIError:
    """An Anymail error as Resend would raise it for an HTTP ``status``."""
    response = requests.Response()
    response.status_code = status
    response._content = b"{}"
    return AnymailRequestsAPIError(response=response)


class TestRender:
    def test_html_and_text_parts(self):
        html, text = services.render("test", language="en")
        assert "Email is working" in html
        assert "Email is working" in text
        assert "<" not in text

    def test_language_picks_the_translation(self):
        th_html, _ = services.render("test", language="th")
        assert "อีเมลใช้งานได้" in th_html

    def test_text_falls_back_to_stripped_html_without_a_txt_template(self, tmp_path):
        with mock.patch.object(
            services,
            "render_to_string",
            side_effect=lambda name, ctx: (
                "<p>Hi</p>"
                if name.endswith(".html")
                else (_ for _ in ()).throw(services.TemplateDoesNotExist(name))
            ),
        ):
            html, text = services.render("whatever")
        assert html == "<p>Hi</p>"
        assert text == "Hi"


class TestSendEmailTask:
    def run(self, **extra):
        return send_email.apply(
            kwargs={
                "to": ["a@example.com"],
                "subject": "Hello",
                "template": "test",
                "language": "en",
                **extra,
            },
        )

    def test_sends_a_multipart_message(self):
        result = self.run(tags=["x"], reply_to=["r@example.com"])
        assert result.successful()
        (message,) = mail.outbox
        assert message.to == ["a@example.com"]
        assert message.reply_to == ["r@example.com"]
        assert message.subject.endswith("Hello")
        assert message.alternatives[0][1] == "text/html"
        assert message.tags == ["x"]

    def test_server_error_is_retried(self):
        with mock.patch.object(services, "deliver", side_effect=api_error(503)):
            with mock.patch.object(
                send_email,
                "retry",
                side_effect=RuntimeError("retry"),
            ) as retry:
                result = self.run()
        assert retry.called
        assert isinstance(result.result, RuntimeError)

    def test_rate_limit_and_connection_errors_are_retried(self):
        for error in (api_error(429), requests.ConnectionError("down")):
            with mock.patch.object(services, "deliver", side_effect=error):
                with mock.patch.object(
                    send_email,
                    "retry",
                    side_effect=RuntimeError,
                ) as retry:
                    self.run()
            assert retry.called, error

    def test_client_error_is_not_retried(self):
        with mock.patch.object(services, "deliver", side_effect=api_error(422)):
            with mock.patch.object(send_email, "retry") as retry:
                result = self.run()
        assert not retry.called
        assert result.failed()


class TestQueueEmail:
    def test_queues_after_commit_with_normalised_arguments(
        self,
        django_capture_on_commit_callbacks,
    ):
        with mock.patch("money_plan.mailer.api.send_email") as task:
            with django_capture_on_commit_callbacks(execute=True):
                queue_email(
                    to="a@example.com",
                    subject="S",
                    template="test",
                    reply_to="r@example.com",
                )
        task.delay.assert_called_once()
        kwargs = task.delay.call_args.kwargs
        assert kwargs["to"] == ["a@example.com"]
        assert kwargs["reply_to"] == ["r@example.com"]

    def test_nothing_is_queued_before_commit(self, django_capture_on_commit_callbacks):
        with mock.patch("money_plan.mailer.api.send_email") as task:
            with django_capture_on_commit_callbacks(execute=False):
                queue_email(to="a@example.com", subject="S", template="test")
            assert not task.delay.called

    def test_needs_a_recipient_and_a_json_context(self):
        with pytest.raises(ValueError, match="recipient"):
            queue_email(to=[], subject="S", template="test")
        with pytest.raises(TypeError, match="JSON"):
            queue_email(
                to="a@example.com",
                subject="S",
                template="test",
                context={"x": object()},
            )


def test_send_test_email_command_queues_the_task(django_capture_on_commit_callbacks):
    with mock.patch("money_plan.mailer.api.send_email") as task:
        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_test_email", "me@example.com")
    assert task.delay.call_args.kwargs["template"] == "test"


def make_log(**fields) -> EmailLog:
    return EmailLog.objects.create(
        to=fields.pop("to", "a@example.com"),
        template="test",
        subject="S",
        **fields,
    )


class TestEmailLog:
    def test_queue_email_creates_a_queued_row_and_passes_its_id(
        self,
        django_capture_on_commit_callbacks,
    ):
        user = UserFactory()
        with mock.patch("money_plan.mailer.api.send_email") as task:
            with django_capture_on_commit_callbacks(execute=True):
                log = queue_email(
                    to=["a@example.com", "b@example.com"],
                    subject="S",
                    template="test",
                    user=user,
                )
        assert log.status == EmailLog.Status.QUEUED
        assert log.to == "a@example.com, b@example.com"
        assert log.user == user
        assert task.delay.call_args.kwargs["log_id"] == log.pk

    def test_task_marks_sent_and_stores_the_provider_id(self):
        log = make_log()
        with mock.patch.object(services, "deliver", return_value="msg-1"):
            send_email.apply(
                kwargs={
                    "to": ["a@example.com"],
                    "subject": "S",
                    "template": "test",
                    "log_id": log.pk,
                },
            )
        log.refresh_from_db()
        assert (log.status, log.message_id, log.attempts) == ("sent", "msg-1", 1)
        assert log.sent_at

    def test_the_sent_body_is_stored_even_when_the_provider_then_fails(self):
        log = make_log()
        with mock.patch.object(services, "EmailMultiAlternatives") as message:
            message.return_value.send.side_effect = api_error(422)
            send_email.apply(
                kwargs={
                    "to": ["a@example.com"],
                    "subject": "S",
                    "template": "test",
                    "language": "en",
                    "log_id": log.pk,
                },
            )
        log.refresh_from_db()
        assert "Email is working" in log.body_html
        assert "Email is working" in log.body_text
        assert log.status == "failed"

    def test_retry_keeps_it_queued_with_the_error(self):
        log = make_log()
        with mock.patch.object(services, "deliver", side_effect=api_error(503)):
            with mock.patch.object(send_email, "retry", side_effect=RuntimeError):
                send_email.apply(
                    kwargs={
                        "to": ["a@example.com"],
                        "subject": "S",
                        "template": "test",
                        "log_id": log.pk,
                    },
                )
        log.refresh_from_db()
        assert log.status == "queued"
        assert log.error

    def test_permanent_failure_marks_failed(self):
        log = make_log()
        with mock.patch.object(services, "deliver", side_effect=api_error(422)):
            send_email.apply(
                kwargs={
                    "to": ["a@example.com"],
                    "subject": "S",
                    "template": "test",
                    "log_id": log.pk,
                },
            )
        log.refresh_from_db()
        assert log.status == "failed"
        assert log.error


class TestDedupe:
    def queue(self, django_capture_on_commit_callbacks, key="monthly:2026-10:1"):
        with mock.patch("money_plan.mailer.api.send_email") as task:
            with django_capture_on_commit_callbacks(execute=True):
                log = queue_email(
                    to="a@example.com",
                    subject="S",
                    template="test",
                    dedupe_key=key,
                )
        return log, task

    def test_second_call_with_the_same_key_is_skipped(
        self,
        django_capture_on_commit_callbacks,
    ):
        first, _ = self.queue(django_capture_on_commit_callbacks)
        second, task = self.queue(django_capture_on_commit_callbacks)
        assert first
        assert second is None
        assert not task.delay.called
        assert EmailLog.objects.count() == 1

    def test_a_failed_mail_is_queued_again(self, django_capture_on_commit_callbacks):
        first, _ = self.queue(django_capture_on_commit_callbacks)
        first.advance("failed", error="x", attempts=3)
        again, task = self.queue(django_capture_on_commit_callbacks)
        assert again.pk == first.pk
        assert (again.status, again.attempts, again.error) == ("queued", 0, "")
        assert task.delay.called

    def test_different_keys_do_not_collide(self, django_capture_on_commit_callbacks):
        self.queue(django_capture_on_commit_callbacks, "k1")
        other, _ = self.queue(django_capture_on_commit_callbacks, "k2")
        assert other


class TestWebhook:
    def event(self, event_type, message_id="msg-1", description=None):
        from anymail.signals import AnymailTrackingEvent

        return AnymailTrackingEvent(
            event_type=event_type,
            message_id=message_id,
            description=description,
        )

    def fire(self, event):
        from anymail.signals import tracking

        tracking.send(sender=object, event=event, esp_name="Resend")

    def test_delivered_then_bounce_ends_as_bounced(self):
        log = make_log(message_id="msg-1", status="sent")
        self.fire(self.event("delivered"))
        log.refresh_from_db()
        assert log.status == "delivered"
        self.fire(self.event("bounced", description="mailbox full"))
        log.refresh_from_db()
        assert (log.status, log.error) == ("bounced", "mailbox full")

    def test_a_late_delivery_event_does_not_hide_a_bounce(self):
        log = make_log(message_id="msg-1", status="bounced")
        self.fire(self.event("delivered"))
        log.refresh_from_db()
        assert log.status == "bounced"

    def test_delay_complaint_and_unknown_message(self):
        log = make_log(message_id="msg-1", status="sent")
        self.fire(self.event("deferred"))
        log.refresh_from_db()
        assert log.status == "delayed"
        self.fire(self.event("complained"))
        log.refresh_from_db()
        assert log.status == "complained"
        self.fire(self.event("delivered", message_id="nobody"))  # no row: ignored

    def test_opens_and_clicks_are_ignored(self):
        log = make_log(message_id="msg-1", status="delivered")
        self.fire(self.event("opened"))
        self.fire(self.event("clicked"))
        log.refresh_from_db()
        assert log.status == "delivered"

    def test_webhook_lives_at_webhooks_and_rejects_unsigned_posts(
        self,
        client,
        settings,
    ):
        from django.urls import reverse

        settings.ANYMAIL = {
            **settings.ANYMAIL,
            "RESEND_SIGNING_SECRET": "whsec_dGVzdA==",
        }
        assert reverse("resend_webhook") == "/webhooks/"
        resp = client.post("/webhooks/", data="{}", content_type="application/json")
        assert resp.status_code in (400, 401, 403)


def test_purge_removes_only_old_logs():
    from datetime import timedelta

    from django.utils import timezone

    old, new = make_log(), make_log()
    EmailLog.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=100),
    )
    assert purge_old_logs() == 1
    assert list(EmailLog.objects.all()) == [new]


def test_deleting_a_user_deletes_their_mail_log():
    user = UserFactory()
    make_log(user=user)
    user.delete()
    assert not EmailLog.objects.exists()


def test_admin_shows_the_stored_mail_in_a_sandboxed_frame(admin_client):
    from django.urls import reverse

    log = make_log(body_html='<p>hi</p><script>alert("x")</script>', body_text="hi")
    html = admin_client.get(
        reverse("admin:mailer_emaillog_change", args=[log.pk]),
    ).content.decode()
    assert "<iframe sandbox" in html
    assert "<script>alert" not in html  # escaped inside srcdoc, never live markup
    assert (
        admin_client.post(
            reverse("admin:mailer_emaillog_change", args=[log.pk]),
            {},
        ).status_code
        == 403
    )
