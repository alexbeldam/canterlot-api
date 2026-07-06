from dataclasses import dataclass
from datetime import datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, Field

from canterlot.models.club import ClubModel, ClubNameStr, ClubSlugStr
from canterlot.models.enums import ClubOnboardingStatus, JoinPolicy, UserRole
from canterlot.models.user import UsernameStr
from canterlot.utils.format import LanguageStr


class ClubCreateRequest(BaseModel):
    name: ClubNameStr
    description: str | None = Field(
        default=None,
        examples=["A cozy corner for reading historical fiction and sharing tea recipes."],
    )
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    preferred_languages: list[LanguageStr] = Field(default_factory=list)


@dataclass(frozen=True)
class ClubOnboarding:
    club_name: ClubNameStr
    status: ClubOnboardingStatus


class ClubMemberDTO(BaseModel):
    username: UsernameStr
    role: UserRole
    joined_at: datetime


class PendingApprovalDTO(BaseModel):
    username: UsernameStr
    requested_at: datetime


class ClubResponse(BaseModel):
    slug: ClubSlugStr
    name: ClubNameStr
    description: str | None = None
    join_policy: JoinPolicy
    allow_suggestions: bool
    preferred_languages: list[LanguageStr]
    members: list[ClubMemberDTO]
    created_at: datetime

    @classmethod
    def from_model(
        cls,
        club: ClubModel,
        user_usernames: dict[PydanticObjectId, UsernameStr],
    ) -> "ClubResponse":
        return cls(
            slug=club.slug,
            name=club.name,
            description=club.description,
            join_policy=club.join_policy,
            allow_suggestions=club.allow_suggestions,
            preferred_languages=club.preferred_languages,
            members=[
                ClubMemberDTO(username=user_usernames[member.user_id], role=member.role, joined_at=member.joined_at)
                for member in club.members
            ],
            created_at=club.created_at,
        )


class ClubDetailResponse(ClubResponse):
    """`ClubResponse` plus fields only ever shown to an `OWNER`/`ADMIN` caller, never to plain members."""

    pending_approvals: list[PendingApprovalDTO]

    @classmethod
    def from_model_with_pending(
        cls,
        club: ClubModel,
        user_usernames: dict[PydanticObjectId, UsernameStr],
        pending_usernames: dict[PydanticObjectId, UsernameStr],
    ) -> "ClubDetailResponse":
        base = ClubResponse.from_model(club, user_usernames)

        return cls(
            **base.model_dump(),
            pending_approvals=[
                PendingApprovalDTO(
                    username=pending_usernames[pending.user_id],
                    requested_at=pending.requested_at,
                )
                for pending in club.pending_approvals
            ],
        )
