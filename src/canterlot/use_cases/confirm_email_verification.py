from beanie import PydanticObjectId

from canterlot.dto.auth import ConfirmEmailVerificationRequest
from canterlot.exceptions.auth import UnauthenticatedCodeVerificationError
from canterlot.models.user import UserModel
from canterlot.services import UserService, VerificationService
from canterlot.types import VerificationScope
from canterlot.utils import decode_action_link_token, get_logger

logger = get_logger(__name__)


class ConfirmEmailVerificationUseCase:
    def __init__(
        self,
        verification_service: VerificationService,
        user_service: UserService,
    ) -> None:
        self.__verification_service = verification_service
        self.__user_service = user_service

    async def execute(
        self,
        payload: ConfirmEmailVerificationRequest,
        current_user: UserModel | None = None,
    ) -> None:
        log = logger.bind(
            has_token=bool(payload.token),
            has_code=bool(payload.code),
            user_id=str(current_user.id) if current_user else None,
        )
        log.info("Executing confirm email verification use case")

        # ---------------------------------------------------------
        # 1. Resolve Target Identity & Verification Code
        # ---------------------------------------------------------
        if payload.token:
            token_data = decode_action_link_token(payload.token)
            user_id = token_data.user_id
            code = token_data.code
        elif payload.code:
            if not current_user:
                log.info("Email verification confirmation rejected: unauthenticated code attempt")
                raise UnauthenticatedCodeVerificationError(
                    "An active login session is required when verifying via code."
                )
            user_id = PydanticObjectId(current_user.id)
            code = payload.code

        log = log.bind(target_user_id=str(user_id))

        # ---------------------------------------------------------
        # 2. Validate Code & Enforce Rate Limits
        # ---------------------------------------------------------
        await self.__verification_service.validate_code(
            code=code,
            user_id=user_id,
            scope=VerificationScope.EMAIL,
        )

        # ---------------------------------------------------------
        # 3. Mark Email as Verified via UserService
        # ---------------------------------------------------------
        await self.__user_service.mark_email_as_verified(user_id=user_id)

        log.info("Email verification confirmed successfully")
