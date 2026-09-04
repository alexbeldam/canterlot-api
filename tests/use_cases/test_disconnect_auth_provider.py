from unittest.mock import AsyncMock

import pytest

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import AuthProviderContext
from canterlot.types import AuthProviderName
from canterlot.use_cases.disconnect_auth_provider import DisconnectAuthProviderUseCase
from tools.factories import UserFactory


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> DisconnectAuthProviderUseCase:
    return DisconnectAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch_service,
    )


def describe_disconnect_auth_provider_use_case():
    async def it_disconnects_provider_and_dispatches_notification(
        use_case: DisconnectAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(name="Twilight Sparkle")

        await use_case.execute(
            user=user,
            provider=AuthProviderName.GOOGLE,
        )

        auth_service.disconnect_provider.assert_awaited_once_with(
            user=user,
            provider=AuthProviderName.GOOGLE,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_PROVIDER_DISCONNECTED
        assert task.to == user.email
        assert isinstance(task.context, AuthProviderContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert task.context.provider_name == "Google"
        assert call_kwargs["prefs"] == user.email_preferences
