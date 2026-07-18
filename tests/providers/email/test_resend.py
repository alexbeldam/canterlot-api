import resend

from canterlot.providers.email import EmailMessage, ResendEmailClient


def describe_name():
    def it_reports_resend_as_provider_name():
        assert ResendEmailClient("re_123").name == "resend"


def describe_send():
    async def it_maps_message_into_resend_payload_and_returns_message_id(monkeypatch):
        captured_payload: dict[str, object] = {}

        def fake_send(payload):
            captured_payload.update(payload)
            return {"id": "email_123"}

        monkeypatch.setattr(resend.Emails, "send", fake_send)

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

    async def it_returns_a_failure_result_when_resend_raises(monkeypatch):
        def raise_error(_payload):
            raise RuntimeError("Resend unavailable")

        monkeypatch.setattr(resend.Emails, "send", raise_error)

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
        assert result.error_message == "Resend unavailable"
