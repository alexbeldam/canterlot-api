from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

from canterlot.types import ClubNameStr, ClubSlugStr, JoinPolicy, LanguageStr


class ClubModel(Document):
    name: ClubNameStr
    description: str | None = None
    slug: Annotated[ClubSlugStr, Indexed(unique=True)]
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    allow_suggestions: bool = True
    preferred_languages: list[LanguageStr] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ownership_transferred_at: datetime | None = None
    protected_former_owner_id: PydanticObjectId | None = None

    class Settings:
        name = "clubs"
