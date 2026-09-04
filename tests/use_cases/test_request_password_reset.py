from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordResetValidationContext
from canterlot.types import VerificationScope, secret_code_adapter
from canterlot.use_cases.request_password_reset import RequestPasswordResetUseCase
from tools.factories import UserFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CODE = secret_code_adapter.validate_python("123456")


@pytest.fixture
def use_case(
    user_service: AsyncMock,
    verification_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> RequestPasswordResetUseCase:
    return RequestPasswordResetUseCase(
        user_service=user_service,
        verification_service=verification_service,
        email_dispatch=email_dispatch_service,
    )


def describe_request_password_reset_use_case():
    async def it_issues_a_code_and_dispatches_a_reset_email_for_an_existing_user(
        use_case: RequestPasswordResetUseCase,
        user_service: AsyncMock,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, name="Twilight Sparkle", hashed_password="hashed")
        user_service.find_by_identifier.return_value = user
        verification_service.create_code.return_value = SOME_CODE

        await use_case.execute("twilight@canterlot.dev")

        user_service.find_by_identifier.assert_awaited_once_with("twilight@canterlot.dev")
        verification_service.create_code.assert_awaited_once_with(
            user_id=SOME_USER_ID,
            scope=VerificationScope.PASSWORD_RESET,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_PASSWORD_RESET
        assert task.to == user.email
        assert isinstance(task.context, PasswordResetValidationContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert task.context.is_creation is False
        assert call_kwargs["prefs"] == user.email_preferences

    async def it_marks_the_email_as_a_first_time_password_creation_when_the_user_has_no_password(
        use_case: RequestPasswordResetUseCase,
        user_service: AsyncMock,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, hashed_password=None)
        user_service.find_by_identifier.return_value = user
        verification_service.create_code.return_value = SOME_CODE

        await use_case.execute("twilight")

        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        assert call_kwargs["task"].context.is_creation is True

    async def it_silently_completes_when_no_user_matches_the_identifier(
        use_case: RequestPasswordResetUseCase,
        user_service: AsyncMock,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user_service.find_by_identifier.return_value = None

        await use_case.execute("nobody@canterlot.dev")

        verification_service.create_code.assert_not_called()
        email_dispatch_service.dispatch.assert_not_called()
