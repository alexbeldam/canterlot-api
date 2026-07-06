from datetime import UTC, datetime
from typing import Annotated

import shortuuid
from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

from canterlot.utils.format import NormalizedEmailStr

from .enums import InviteType


class InviteModel(Document):
    id: str = Field(default_factory=lambda: shortuuid.random(length=10), alias="_id")  # type: ignore[assignment]
    club_id: PydanticObjectId
    created_by: PydanticObjectId | None = None
    target_email: Annotated[NormalizedEmailStr, Indexed()] | None = None
    type: InviteType = InviteType.PUBLIC
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    uses_count: int = Field(default=0, ge=0)
    is_active: bool = True

    class Settings:
        name = "invites"
        is_root = True
