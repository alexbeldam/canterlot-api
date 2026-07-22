from unittest.mock import AsyncMock, MagicMock

import pytest

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.factories import UserFactory
from canterlot.types import AuthProviderName
from canterlot.use_cases.revoke_auth_provider import RevokeAuthProviderUseCase


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> RevokeAuthProviderUseCase:
    return RevokeAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch_service,
    )


def describe_revoke_auth_provider_use_case():
    async def it_revokes_provider_link_and_dispatches_locked_out_email_when_locked_out(
        use_case: RevokeAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(name="Twilight Sparkle")
        result = MagicMock()
        result.user = user
        result.is_locked_out = True
        auth_service.revoke_provider_link.return_value = result

        await use_case.execute(
            provider=AuthProviderName.GOOGLE,
            external_id="google-123",
        )

        auth_service.revoke_provider_link.assert_awaited_once_with(
            provider=AuthProviderName.GOOGLE,
            external_id="google-123",
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_LOCKED_OUT
        assert task.to == user.email
        assert task.context.recipient_name == "Twilight Sparkle"

    async def it_revokes_provider_link_without_email_when_not_locked_out(
        use_case: RevokeAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(name="Twilight Sparkle")
        result = MagicMock()
        result.user = user
        result.is_locked_out = False
        auth_service.revoke_provider_link.return_value = result

        await use_case.execute(
            provider=AuthProviderName.GOOGLE,
            external_id="google-123",
        )

        auth_service.revoke_provider_link.assert_awaited_once_with(
            provider=AuthProviderName.GOOGLE,
            external_id="google-123",
        )
        email_dispatch_service.dispatch.assert_not_called()

    async def it_handles_revocation_when_no_user_found(
        use_case: RevokeAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        result = MagicMock()
        result.user = None
        result.is_locked_out = False
        auth_service.revoke_provider_link.return_value = result

        await use_case.execute(
            provider=AuthProviderName.GOOGLE,
            external_id="missing-id",
        )

        auth_service.revoke_provider_link.assert_awaited_once_with(
            provider=AuthProviderName.GOOGLE,
            external_id="missing-id",
        )
        email_dispatch_service.dispatch.assert_not_called()
