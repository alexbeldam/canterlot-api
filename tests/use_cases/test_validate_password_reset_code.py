from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.auth import ValidatePasswordResetCodeRequest
from canterlot.types import TokenType, VerificationScope, secret_code_adapter
from canterlot.use_cases.validate_password_reset_code import ValidatePasswordResetCodeUseCase
from canterlot.utils import decode_jwt_payload
from canterlot.utils.security import encode_action_link_token

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CODE = secret_code_adapter.validate_python("123456")


@pytest.fixture
def use_case(
    user_service: AsyncMock,
    verification_service: AsyncMock,
) -> ValidatePasswordResetCodeUseCase:
    return ValidatePasswordResetCodeUseCase(
        user_service=user_service,
        verification_service=verification_service,
    )


def describe_validate_password_reset_code_use_case():
    async def it_validates_via_a_signed_action_link_token_and_mints_a_reset_token(
        use_case: ValidatePasswordResetCodeUseCase,
        user_service: AsyncMock,
        verification_service: AsyncMock,
    ):
        token = encode_action_link_token(SOME_USER_ID, SOME_CODE)
        payload = ValidatePasswordResetCodeRequest(token=token)

        reset_token = await use_case.execute(payload)

        verification_service.validate_code.assert_awaited_once_with(
            code=SOME_CODE,
            user_id=SOME_USER_ID,
            scope=VerificationScope.PASSWORD_RESET,
        )
        user_service.get_id_by_identifier.assert_not_called()

        claims = decode_jwt_payload(reset_token)
        assert claims["sub"] == str(SOME_USER_ID)
        assert claims["type"] == TokenType.RESET

    async def it_validates_via_an_identifier_and_manually_entered_code(
        use_case: ValidatePasswordResetCodeUseCase,
        user_service: AsyncMock,
        verification_service: AsyncMock,
    ):
        user_service.get_id_by_identifier.return_value = SOME_USER_ID
        payload = ValidatePasswordResetCodeRequest(identifier="twilight@canterlot.dev", code=SOME_CODE)

        reset_token = await use_case.execute(payload)

        user_service.get_id_by_identifier.assert_awaited_once_with("twilight@canterlot.dev")
        verification_service.validate_code.assert_awaited_once_with(
            code=SOME_CODE,
            user_id=SOME_USER_ID,
            scope=VerificationScope.PASSWORD_RESET,
        )

        claims = decode_jwt_payload(reset_token)
        assert claims["sub"] == str(SOME_USER_ID)
        assert claims["type"] == TokenType.RESET
