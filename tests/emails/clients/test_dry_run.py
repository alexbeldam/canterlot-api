from canterlot.emails import EmailMessage
from canterlot.emails.clients import DryRunEmailClient


def describe_send():
    async def it_returns_a_successful_dry_run_result():
        client = DryRunEmailClient()

        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Hello",
                html="<p>Hello</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert result.success is True
        assert result.dry_run is True
        assert result.disabled is False
        assert result.provider_message_id is None
