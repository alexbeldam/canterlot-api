from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import LunaProviderActionContext
from canterlot.factories import UserFactory
from canterlot.types import AuthProviderName
from canterlot.use_cases.link_auth_provider import LinkAuthProviderUseCase

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> LinkAuthProviderUseCase:
    return LinkAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch_service,
    )


def describe_link_auth_provider_use_case():
    async def it_links_provider_and_dispatches_notification(
        use_case: LinkAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, name="Twilight Sparkle")

        await use_case.execute(
            user=user,
            provider=AuthProviderName.GOOGLE,
            credential="valid-auth-code",
            redirect_uri="https://canterlot.dev/callback",
        )

        auth_service.link_provider.assert_awaited_once_with(
            user_id=user.id,
            provider=AuthProviderName.GOOGLE,
            credential="valid-auth-code",
            redirect_uri="https://canterlot.dev/callback",
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_PROVIDER_LINKED
        assert task.to == user.email
        assert isinstance(task.context, LunaProviderActionContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert task.context.provider_name == "Google"
        assert call_kwargs["prefs"] == user.email_preferences

    async def it_supports_linking_without_redirect_uri(
        use_case: LinkAuthProviderUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, name="Twilight Sparkle")

        await use_case.execute(
            user=user,
            provider=AuthProviderName.GOOGLE,
            credential="valid-auth-code",
        )

        auth_service.link_provider.assert_awaited_once_with(
            user_id=user.id,
            provider=AuthProviderName.GOOGLE,
            credential="valid-auth-code",
            redirect_uri=None,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
