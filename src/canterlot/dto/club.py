from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, model_validator

from canterlot.dto.user import AvatarDTO, BadgeDTO
from canterlot.models.club import (
    OWNERSHIP_RECLAIM_WINDOW,
    OWNERSHIP_TRANSFER_COOLDOWN,
    ClubModel,
    ClubNameStr,
    ClubSlugStr,
    MemberSchema,
)
from canterlot.models.user import PersonNameStr, UserModel, UsernameStr
from canterlot.types import ClubOnboardingStatus, JoinPolicy, LanguageStr, MemberRole


class ClubCreateRequest(BaseModel):
    name: ClubNameStr
    description: str | None = Field(
        default=None,
        examples=["A cozy corner for reading historical fiction and sharing tea recipes."],
    )
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    preferred_languages: list[LanguageStr] = Field(default_factory=list)


class ClubSettingsUpdateRequest(BaseModel):
    name: ClubNameStr | None = None
    description: str | None = Field(
        default=None,
        examples=["A cozy corner for reading historical fiction and sharing tea recipes."],
    )
    join_policy: JoinPolicy | None = None
    allow_suggestions: bool | None = None
    preferred_languages: list[LanguageStr] | None = None

    @model_validator(mode="after")
    def check_at_least_one_field_provided(self) -> "ClubSettingsUpdateRequest":
        fields = (self.name, self.description, self.join_policy, self.allow_suggestions, self.preferred_languages)
        if all(value is None for value in fields):
            raise ValueError("At least one setting must be provided.")
        return self


@dataclass(frozen=True)
class ClubOnboarding:
    club_name: ClubNameStr
    status: ClubOnboardingStatus


class ClubMemberDTO(BaseModel):
    username: UsernameStr
    role: MemberRole
    joined_at: datetime


class ClubMemberProfileResponse(BaseModel):
    username: UsernameStr
    name: PersonNameStr
    role: MemberRole
    joined_at: datetime
    avatar: AvatarDTO | None = None
    generated_avatar_seed: str
    badges: list[BadgeDTO] = Field(default_factory=list)

    @classmethod
    def from_models(cls, user: UserModel, member: MemberSchema) -> "ClubMemberProfileResponse":
        return cls(
            username=user.username,
            name=user.name,
            role=member.role,
            joined_at=member.joined_at,
            avatar=AvatarDTO.from_model(user.avatar) if user.avatar else None,
            generated_avatar_seed=user.generated_avatar_seed,
            badges=[BadgeDTO.from_model(badge) for badge in user.badges],
        )


class ChangeMemberRoleRequest(BaseModel):
    role: Literal[MemberRole.ADMIN, MemberRole.MEMBER]


class OwnershipTransferRequest(BaseModel):
    new_owner_username: UsernameStr


class OwnershipTransferResponse(BaseModel):
    reclaim_deadline: datetime


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
        role_order = list(MemberRole)
        sorted_members = sorted(
            club.members,
            key=lambda member: (role_order.index(member.role), user_usernames[member.user_id]),
        )

        return cls(
            slug=club.slug,
            name=club.name,
            description=club.description,
            join_policy=club.join_policy,
            allow_suggestions=club.allow_suggestions,
            preferred_languages=club.preferred_languages,
            members=[
                ClubMemberDTO(username=user_usernames[member.user_id], role=member.role, joined_at=member.joined_at)
                for member in sorted_members
            ],
            created_at=club.created_at,
        )


class ClubDetailResponse(ClubResponse):
    """`ClubResponse` plus fields only ever shown to an `OWNER`/`ADMIN` caller, never to plain members."""

    pending_approvals: list[PendingApprovalDTO]
    protected_former_owner: UsernameStr | None = None
    active_reclaim_deadline: datetime | None = None

    @classmethod
    def from_model_with_pending(
        cls,
        club: ClubModel,
        user_usernames: dict[PydanticObjectId, UsernameStr],
        pending_usernames: dict[PydanticObjectId, UsernameStr],
        viewer_id: PydanticObjectId,
    ) -> "ClubDetailResponse":
        base = ClubResponse.from_model(club, user_usernames)
        sorted_pending = sorted(club.pending_approvals, key=lambda pending: pending.requested_at)

        now = datetime.now(UTC)
        protected_former_owner = None
        active_reclaim_deadline = None
        if club.protected_former_owner_id is not None and club.ownership_transferred_at is not None:
            if now - club.ownership_transferred_at < OWNERSHIP_TRANSFER_COOLDOWN:
                protected_former_owner = user_usernames.get(club.protected_former_owner_id)
            if (
                viewer_id == club.protected_former_owner_id
                and now - club.ownership_transferred_at < OWNERSHIP_RECLAIM_WINDOW
            ):
                active_reclaim_deadline = club.ownership_transferred_at + OWNERSHIP_RECLAIM_WINDOW

        return cls(
            **base.model_dump(),
            pending_approvals=[
                PendingApprovalDTO(
                    username=pending_usernames[pending.user_id],
                    requested_at=pending.requested_at,
                )
                for pending in sorted_pending
            ],
            protected_former_owner=protected_former_owner,
            active_reclaim_deadline=active_reclaim_deadline,
        )
