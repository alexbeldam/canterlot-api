from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from canterlot.dto.auth import AccessTokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordChangedContext
from canterlot.use_cases.change_password import (
    ChangePasswordUseCase,
    ChangePasswordUseCaseResult,
)
from tools.factories import UserFactory

DEFAULT_HASHED_PASSWORD = "hashed_password"
DEFAULT_PASSWORD = "password"


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch_service,
    )


def describe_change_password_use_case():
    async def it_changes_password_dispatches_security_email_and_returns_tokens(
        use_case: ChangePasswordUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(name="Twilight Sparkle", hashed_password=DEFAULT_HASHED_PASSWORD)
        current_password = SecretStr(DEFAULT_PASSWORD)
        new_password = SecretStr("NewSecurePassword456!")

        token_mock = MagicMock()
        token_mock.access_token = "mock-access-token"
        token_mock.token_type = "Bearer"
        token_mock.refresh_token = "mock-refresh-token"
        auth_service.change_password.return_value = token_mock

        result = await use_case.execute(
            user=user,
            current_password=current_password,
            new_password=new_password,
        )

        assert isinstance(result, ChangePasswordUseCaseResult)
        assert isinstance(result.response, AccessTokenResponse)
        assert result.response.access_token == "mock-access-token"
        assert result.response.token_type == "Bearer"
        assert result.refresh_token == "mock-refresh-token"

        auth_service.change_password.assert_awaited_once_with(
            user=user,
            current_password=current_password,
            new_password=new_password,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_PASSWORD_CHANGED
        assert task.to == user.email
        assert isinstance(task.context, PasswordChangedContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert task.context.is_creation is False
        assert task.context.action == "changed"
        assert call_kwargs["prefs"] == user.email_preferences
