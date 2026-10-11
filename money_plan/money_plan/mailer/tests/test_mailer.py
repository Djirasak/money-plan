from __future__ import annotations

from unittest import mock

import pytest
import requests
from anymail.exceptions import AnymailRequestsAPIError
from django.core import mail
from django.core.management import call_command

from money_plan.mailer import services
from money_plan.mailer.api import queue_email
from money_plan.mailer.tasks import send_email

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
