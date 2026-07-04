from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field, StringConstraints, model_validator

from canterlot.utils.format import LanguageStr, NonEmptyStr

from .enums import ClubOnboardingStatus, JoinPolicy, UserRole

type ClubNameStr = Annotated[NonEmptyStr, StringConstraints(min_length=3, max_length=50)]


class MemberSchema(BaseModel):
    user_id: PydanticObjectId
    role: UserRole = UserRole.USER
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CatalogEntryModel(BaseModel):
    book_id: PydanticObjectId
    suggested_by: PydanticObjectId
    suggested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClubModel(Document):
    name: ClubNameStr
    description: str | None = None
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    allow_suggestions: bool = True
    preferred_languages: list[LanguageStr] = Field(default_factory=list)
    members: list[MemberSchema] = Field(default_factory=list)
    banned_users: list[PydanticObjectId] = Field(default_factory=list)
    pending_approvals: list[PydanticObjectId] = Field(default_factory=list)
    catalog: list[CatalogEntryModel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "clubs"

    @model_validator(mode="after")
    def verify_unique_membership_states(self):
        member_ids = {m.user_id for m in self.members}
        banned_ids = set(self.banned_users)
        pending_ids = set(self.pending_approvals)

        if intersection := member_ids.intersection(banned_ids):
            raise ValueError(f"Users cannot be active members and banned: {intersection}")
        if intersection := member_ids.intersection(pending_ids):
            raise ValueError(f"Users cannot be active members and pending: {intersection}")
        if intersection := banned_ids.intersection(pending_ids):
            raise ValueError(f"Users cannot be banned and pending approval: {intersection}")

        return self


@dataclass(frozen=True)
class ClubOnboarding:
    club_name: ClubNameStr
    status: ClubOnboardingStatus


class ClubCreateRequest(BaseModel):
    name: ClubNameStr
    description: str | None = None
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    preferred_languages: list[LanguageStr] = Field(default_factory=list)
