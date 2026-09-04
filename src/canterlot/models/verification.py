import hashlib
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import Field, validate_call
from pymongo import ASCENDING, IndexModel

from canterlot.types import SecretVerificationCode, VerificationScope


class VerificationCodeModel(Document):
    code_hash: str
    user_id: PydanticObjectId
    scope: VerificationScope
    attempts: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    is_active: bool = True

    class Settings:
        name = "verification_codes"

        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [
                    ("user_id", ASCENDING),
                    ("scope", ASCENDING),
                    ("code_hash", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                name="user_scope_hash_lookup_idx",
            ),
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expiration_idx",
            ),
        ]

    @staticmethod
    @validate_call
    def hash_code(code: SecretVerificationCode, user_id: PydanticObjectId) -> str:
        salted = f"{user_id}:{code.get_secret_value()}"

        return hashlib.sha256(salted.encode("utf-8")).hexdigest()

    @staticmethod
    def build(
        code: SecretVerificationCode,
        user_id: PydanticObjectId,
        scope: VerificationScope,
    ) -> "VerificationCodeModel":
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=scope.ttl_minutes)
        hashed = VerificationCodeModel.hash_code(code, user_id)

        return VerificationCodeModel(code_hash=hashed, user_id=user_id, scope=scope, expires_at=expires_at)
