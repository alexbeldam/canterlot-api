from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.dto.auth import TokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordChangedContext
from canterlot.use_cases.reset_password import ResetPasswordUseCase
from tools.factories import UserFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> ResetPasswordUseCase:
    return ResetPasswordUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch_service,
    )


def describe_reset_password_use_case():
    async def it_resets_the_password_and_dispatches_a_confirmation_email(
        use_case: ResetPasswordUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, name="Twilight Sparkle", hashed_password="hashed")
        new_password = SecretStr("NewSecurePassword456!")
        tokens = TokenResponse(access_token="access-token", refresh_token="refresh-token")
        auth_service.set_password.return_value = tokens

        result = await use_case.execute(user, new_password)

        assert result is tokens

        auth_service.set_password.assert_awaited_once_with(
            user=user,
            password=new_password,
            is_reset=True,
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
        assert call_kwargs["prefs"] == user.email_preferences

    async def it_marks_the_confirmation_email_as_a_first_time_password_creation(
        use_case: ResetPasswordUseCase,
        auth_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, hashed_password=None)
        new_password = SecretStr("NewSecurePassword456!")
        auth_service.set_password.return_value = TokenResponse(access_token="a", refresh_token="r")

        await use_case.execute(user, new_password)

        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        assert call_kwargs["task"].context.is_creation is True
