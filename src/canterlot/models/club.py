from datetime import UTC, datetime
from typing import Annotated, ClassVar

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field, model_validator
from pymongo import ASCENDING, IndexModel

from canterlot.types import ClubNameStr, ClubSlugStr, JoinPolicy, LanguageStr, MemberSchema


class PendingApprovalSchema(BaseModel):
    user_id: PydanticObjectId
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CatalogEntryModel(BaseModel):
    book_id: PydanticObjectId
    suggested_by: PydanticObjectId
    suggested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClubModel(Document):
    name: ClubNameStr
    description: str | None = None
    slug: Annotated[ClubSlugStr, Indexed(unique=True)]
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    allow_suggestions: bool = True
    preferred_languages: list[LanguageStr] = Field(default_factory=list)
    members: list[MemberSchema] = Field(default_factory=list)
    banned_users: list[PydanticObjectId] = Field(default_factory=list)
    pending_approvals: list[PendingApprovalSchema] = Field(default_factory=list)
    catalog: list[CatalogEntryModel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ownership_transferred_at: datetime | None = None
    protected_former_owner_id: PydanticObjectId | None = None

    class Settings:
        name = "clubs"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("members.user_id", ASCENDING)], name="global_member_search_idx"),
        ]

    @model_validator(mode="after")
    def verify_unique_membership_states(self):
        member_ids = {m.user_id for m in self.members}
        banned_ids = set(self.banned_users)
        pending_ids = {p.user_id for p in self.pending_approvals}

        if intersection := member_ids.intersection(banned_ids):
            raise ValueError(f"Users cannot be active members and banned: {intersection}")
        if intersection := member_ids.intersection(pending_ids):
            raise ValueError(f"Users cannot be active members and pending: {intersection}")
        if intersection := banned_ids.intersection(pending_ids):
            raise ValueError(f"Users cannot be banned and pending approval: {intersection}")

        return self
