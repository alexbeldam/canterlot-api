from datetime import UTC, datetime
from typing import ClassVar

import shortuuid
from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from canterlot.types import NormalizedEmailStr

from ..types import InviteType


class InviteModel(Document):
    id: str = Field(default_factory=lambda: shortuuid.random(length=10), alias="_id")  # type: ignore[assignment]
    club_id: PydanticObjectId
    created_by: PydanticObjectId | None = None
    target_email: NormalizedEmailStr | None = None
    target_user_id: PydanticObjectId | None = None
    type: InviteType = InviteType.PUBLIC
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    uses_count: int = Field(default=0, ge=0)
    is_active: bool = True

    class Settings:
        name = "invites"
        is_root = True
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [
                    ("club_id", ASCENDING),
                    ("type", ASCENDING),
                    ("is_active", ASCENDING),
                    ("target_email", ASCENDING),
                    ("target_user_id", ASCENDING),
                ],
                name="club_invite_lookup_idx",
            ),
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expiration_idx",
            ),
        ]
