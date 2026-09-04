from beanie import PydanticObjectId
from beanie.operators import Set

from canterlot.models import VerificationCodeModel
from canterlot.repositories import VerificationRepository
from canterlot.types import VerificationScope


class BeanieVerificationRepository(VerificationRepository):
    async def create_and_invalidate_previous(self, verification_code: VerificationCodeModel) -> VerificationCodeModel:
        await VerificationCodeModel.find(
            VerificationCodeModel.user_id == verification_code.user_id,
            VerificationCodeModel.scope == verification_code.scope,
            VerificationCodeModel.is_active == True,
        ).update_many(Set({VerificationCodeModel.is_active: False}))

        return await verification_code.save()

    async def find_active_code(
        self,
        user_id: PydanticObjectId,
        code_hash: str,
        scope: VerificationScope,
    ) -> VerificationCodeModel | None:
        return await VerificationCodeModel.find_one(
            VerificationCodeModel.user_id == user_id,
            VerificationCodeModel.code_hash == code_hash,
            VerificationCodeModel.scope == scope,
            VerificationCodeModel.is_active == True,
        )

    async def deactivate_code_by_id(self, code_id: PydanticObjectId) -> None:
        await VerificationCodeModel.find_one(VerificationCodeModel.id == code_id).update_one(
            Set({VerificationCodeModel.is_active: False})
        )

    async def increment_attempts_and_burn_if_exceeded(
        self,
        user_id: PydanticObjectId,
        scope: VerificationScope,
        max_attempts: int = 5,
    ) -> None:
        raw_collection = VerificationCodeModel.get_pymongo_collection()

        await raw_collection.update_one(
            {
                "user_id": user_id,
                "scope": scope,
                "is_active": True,
            },
            [
                {
                    "$set": {
                        "attempts": {"$add": ["$attempts", 1]},
                        "is_active": {"$lt": [{"$add": ["$attempts", 1]}, max_attempts]},
                    }
                }
            ],
        )
