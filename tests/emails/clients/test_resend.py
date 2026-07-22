import resend
from resend.exceptions import ResendError

from canterlot.emails import EmailMessage
from canterlot.emails.clients import ResendEmailClient


def describe_name():
    def it_reports_resend_as_provider_name():
        assert ResendEmailClient("re_123").name == "resend"


def describe_send():
    async def it_maps_message_into_resend_payload_and_returns_message_id(monkeypatch) -> None:
        captured_payload: dict[str, object] = {}

        async def fake_send(payload):
            captured_payload.update(payload)
            return {"id": "email_123"}

        monkeypatch.setattr(resend.Emails, "send_async", fake_send)

        client = ResendEmailClient("re_live_123")
        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Subject",
                html="<p>Body</p>",
                reply_to="support@canterlot.com.br",
                headers={"List-Unsubscribe": "<https://example.com/u/tok>"},
            )
        )

        assert result.success is True
        assert result.provider_message_id == "email_123"
        assert resend.api_key == "re_live_123"
        assert captured_payload == {
            "from": "Canterlot <onboarding@resend.dev>",
            "to": ["delivered@resend.dev"],
            "subject": "Subject",
            "html": "<p>Body</p>",
            "reply_to": "support@canterlot.com.br",
            "headers": {"List-Unsubscribe": "<https://example.com/u/tok>"},
        }

    async def it_omits_headers_from_payload_if_headers_not_provided(monkeypatch) -> None:
        captured_payload: dict[str, object] = {}

        async def fake_send(payload):
            captured_payload.update(payload)
            return {"id": "email_456"}

        monkeypatch.setattr(resend.Emails, "send_async", fake_send)

        client = ResendEmailClient("re_live_123")
        await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Subject",
                html="<p>Body</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert "headers" not in captured_payload

    async def it_handles_resend_rate_limit_error(monkeypatch):
        async def raise_429(_payload):
            raise ResendError(
                code=429,
                message="429 Too Many Requests: rate_limit_exceeded",
                error_type="rate_limit_error",
                suggested_action="Wait and retry",
            )

        monkeypatch.setattr(resend.Emails, "send_async", raise_429)

        client = ResendEmailClient("re_live_123")
        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Subject",
                html="<p>Body</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert result.success is False
        assert result.disabled is True
        assert result.error_message is not None and "429" in result.error_message

    async def it_handles_general_resend_sdk_error(monkeypatch):
        async def raise_sdk_error(_payload):
            raise ResendError(
                code=401,
                message="Invalid API Key",
                error_type="invalid_api_key",
                suggested_action="Check key",
            )

        monkeypatch.setattr(resend.Emails, "send_async", raise_sdk_error)

        client = ResendEmailClient("re_live_123")
        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Subject",
                html="<p>Body</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert result.success is False
        assert result.disabled is False
        assert result.error_message == "Invalid API Key"

    async def it_returns_a_failure_result_when_unexpected_exception_raised(monkeypatch):
        async def raise_error(_payload):
            raise RuntimeError("Resend infrastructure down")

        monkeypatch.setattr(resend.Emails, "send_async", raise_error)

        client = ResendEmailClient("re_live_123")
        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Subject",
                html="<p>Body</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert result.success is False
        assert result.error_message == "Resend infrastructure down"
