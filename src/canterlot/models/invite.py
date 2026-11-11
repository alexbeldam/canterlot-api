from datetime import UTC, datetime
from typing import ClassVar

import shortuuid
from beanie import Link
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity
from canterlot.types import InviteType, NormalizedEmailStr

from .club import ClubModel
from .user import UserModel


class InviteModel(Entity):
    id: str = Field(default_factory=lambda: shortuuid.random(length=10), alias="_id")  # type: ignore[assignment]
    club: Link[ClubModel]
    created_by: Link[UserModel] | None = None
    target_email: NormalizedEmailStr | None = None
    target_user: Link[UserModel] | None = None
    type: InviteType = InviteType.PUBLIC
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    uses_count: int = Field(default=0, ge=0)
    is_active: bool = True

    class Settings:
        name = "invites"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [
                    ("club.$id", ASCENDING),
                    ("type", ASCENDING),
                    ("is_active", ASCENDING),
                    ("target_email", ASCENDING),
                    ("target_user.$id", ASCENDING),
                ],
                name="club_invite_lookup_idx",
            ),
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expiration_idx",
            ),
        ]
