from canterlot.providers.email.disabled import DisabledEmailClient
from canterlot.providers.email.interfaces import EmailMessage


def describe_send():
    async def it_returns_a_disabled_result_with_reason():
        client = DisabledEmailClient("missing key")

        result = await client.send(
            EmailMessage(
                sender="Canterlot <onboarding@resend.dev>",
                to=["delivered@resend.dev"],
                subject="Hello",
                html="<p>Hello</p>",
                reply_to="support@canterlot.com.br",
            )
        )

        assert result.success is False
        assert result.disabled is True
        assert result.error_message == "missing key"
