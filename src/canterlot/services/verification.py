from datetime import UTC, datetime

from beanie import PydanticObjectId

from canterlot.exceptions import CodeExpiredError, InvalidCodeError
from canterlot.models.verification import VerificationCodeModel
from canterlot.repositories import VerificationRepository
from canterlot.types import SecretVerificationCode, VerificationScope
from canterlot.utils import generate_secure_code


class VerificationService:
    def __init__(self, repo: VerificationRepository):
        self.__repo = repo

    async def create_code(self, user_id: PydanticObjectId, scope: VerificationScope) -> SecretVerificationCode:
        plaintext_code = generate_secure_code()

        code_model = VerificationCodeModel.build(plaintext_code, user_id, scope)

        await self.__repo.create_and_invalidate_previous(code_model)

        return plaintext_code

    async def validate_code(
        self,
        code: SecretVerificationCode,
        user_id: PydanticObjectId,
        scope: VerificationScope,
    ) -> None:
        code_hash = VerificationCodeModel.hash_code(code, user_id)
        code_model = await self.__repo.find_active_code(user_id=user_id, code_hash=code_hash, scope=scope)

        if not code_model:
            from canterlot.config import get_settings

            # Code mismatch or no active code -> register failed attempt on active code
            await self.__repo.increment_attempts_and_burn_if_exceeded(
                user_id=user_id,
                scope=scope,
                max_attempts=get_settings().auth.max_verification_attempts,
            )
            raise InvalidCodeError("The verification code provided is incorrect or has already been used")

        now = datetime.now(UTC)

        if code_model.expires_at <= now:
            raise CodeExpiredError("This verification code has expired. Please request a new one")

        await self.__repo.deactivate_code_by_id(PydanticObjectId(code_model.id))
