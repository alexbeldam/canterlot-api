from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import EmailVerificationContext
from canterlot.exceptions.user import EmailAlreadyVerifiedError
from canterlot.types import VerificationScope, secret_code_adapter
from canterlot.use_cases.request_email_verification import RequestEmailVerificationUseCase
from tools.factories import UserFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CODE = secret_code_adapter.validate_python("123456")


@pytest.fixture
def use_case(
    verification_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> RequestEmailVerificationUseCase:
    return RequestEmailVerificationUseCase(
        verification_service=verification_service,
        email_dispatch=email_dispatch_service,
    )


def describe_request_email_verification_use_case():
    async def it_issues_a_code_and_dispatches_a_verification_email(
        use_case: RequestEmailVerificationUseCase,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID, name="Twilight Sparkle")
        user.email_preferences.verified_at = None
        verification_service.create_code.return_value = SOME_CODE

        await use_case.execute(user)

        verification_service.create_code.assert_awaited_once_with(
            user_id=SOME_USER_ID,
            scope=VerificationScope.EMAIL,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.CELESTIA_VERIFY_EMAIL
        assert task.to == user.email
        assert isinstance(task.context, EmailVerificationContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert call_kwargs["prefs"] == user.email_preferences

    async def it_rejects_the_request_when_the_email_is_already_verified(
        use_case: RequestEmailVerificationUseCase,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID)
        user.email_preferences.verified_at = datetime.now(UTC)

        with pytest.raises(EmailAlreadyVerifiedError):
            await use_case.execute(user)

        verification_service.create_code.assert_not_called()
        email_dispatch_service.dispatch.assert_not_called()
