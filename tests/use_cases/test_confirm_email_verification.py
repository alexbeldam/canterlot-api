from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.auth import ConfirmEmailVerificationRequest
from canterlot.exceptions.auth import UnauthenticatedCodeVerificationError
from canterlot.types import VerificationScope, secret_code_adapter
from canterlot.use_cases.confirm_email_verification import ConfirmEmailVerificationUseCase
from canterlot.utils.security import encode_action_link_token
from tools.factories import UserFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CODE = secret_code_adapter.validate_python("123456")


@pytest.fixture
def use_case(
    verification_service: AsyncMock,
    user_service: AsyncMock,
) -> ConfirmEmailVerificationUseCase:
    return ConfirmEmailVerificationUseCase(
        verification_service=verification_service,
        user_service=user_service,
    )


def describe_confirm_email_verification_use_case():
    async def it_confirms_via_a_signed_action_link_token(
        use_case: ConfirmEmailVerificationUseCase,
        verification_service: AsyncMock,
        user_service: AsyncMock,
    ):
        token = encode_action_link_token(SOME_USER_ID, SOME_CODE)
        payload = ConfirmEmailVerificationRequest(token=token)

        await use_case.execute(payload)

        verification_service.validate_code.assert_awaited_once_with(
            code=SOME_CODE,
            user_id=SOME_USER_ID,
            scope=VerificationScope.EMAIL,
        )
        user_service.mark_email_as_verified.assert_awaited_once_with(user_id=SOME_USER_ID)

    async def it_confirms_via_a_manually_entered_code_for_an_authenticated_user(
        use_case: ConfirmEmailVerificationUseCase,
        verification_service: AsyncMock,
        user_service: AsyncMock,
    ):
        current_user = UserFactory.build(id=SOME_USER_ID)
        payload = ConfirmEmailVerificationRequest(code=SOME_CODE)

        await use_case.execute(payload, current_user=current_user)

        verification_service.validate_code.assert_awaited_once_with(
            code=SOME_CODE,
            user_id=SOME_USER_ID,
            scope=VerificationScope.EMAIL,
        )
        user_service.mark_email_as_verified.assert_awaited_once_with(user_id=SOME_USER_ID)

    async def it_rejects_a_manually_entered_code_with_no_authenticated_user(
        use_case: ConfirmEmailVerificationUseCase,
        verification_service: AsyncMock,
        user_service: AsyncMock,
    ):
        payload = ConfirmEmailVerificationRequest(code=SOME_CODE)

        with pytest.raises(UnauthenticatedCodeVerificationError):
            await use_case.execute(payload, current_user=None)

        verification_service.validate_code.assert_not_called()
        user_service.mark_email_as_verified.assert_not_called()
