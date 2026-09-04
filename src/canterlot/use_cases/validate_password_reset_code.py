from typing import cast

from canterlot.dto.auth import ValidatePasswordResetCodeRequest
from canterlot.services import UserService, VerificationService
from canterlot.types import NormalizedEmailStr, UsernameStr, VerificationScope, secret_code_adapter
from canterlot.utils import create_reset_token, decode_action_link_token, get_logger

logger = get_logger(__name__)


class ValidatePasswordResetCodeUseCase:
    def __init__(
        self,
        user_service: UserService,
        verification_service: VerificationService,
    ):
        self.__user_service = user_service
        self.__verification_service = verification_service

    async def execute(self, payload: ValidatePasswordResetCodeRequest) -> str:
        log = logger.bind(has_token=bool(payload.token))
        log.info("Executing password reset code validation use case")

        # ---------------------------------------------------------
        # 1. Resolve target User ID and Code from Payload
        # ---------------------------------------------------------
        if payload.token:
            token_data = decode_action_link_token(payload.token)
            user_id = token_data.user_id
            code = token_data.code
        else:
            # XOR model validator guarantees both fields are present together
            identifier = cast(NormalizedEmailStr | UsernameStr, payload.identifier)
            code = secret_code_adapter.validate_python(payload.code)

            user_id = await self.__user_service.get_id_by_identifier(identifier)

        # ---------------------------------------------------------
        # 2. Validate Verification Code
        # ---------------------------------------------------------
        await self.__verification_service.validate_code(
            code=code,
            user_id=user_id,
            scope=VerificationScope.PASSWORD_RESET,
        )

        # ---------------------------------------------------------
        # 3. Mint Short-Lived Password Reset JWT
        # ---------------------------------------------------------
        log.info("Password reset verification code validated successfully", user_id=str(user_id))
        return create_reset_token(user_id)
