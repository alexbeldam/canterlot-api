from pydantic import BaseModel, model_validator

from canterlot.models.club import ClubNameStr, ClubSlugStr
from canterlot.models.enums import InviteType, JoinPolicy
from canterlot.models.user import UsernameStr
from canterlot.utils.format import NormalizedEmailStr


class InvitePreviewResponse(BaseModel):
    club_slug: ClubSlugStr
    club_name: ClubNameStr
    join_policy: JoinPolicy
    invite_type: InviteType
    invited_by_username: UsernameStr | None = None


class InviteTokenResponse(BaseModel):
    invite_token: str


class CreateInviteRequest(BaseModel):
    type: InviteType
    email: NormalizedEmailStr | None = None

    @model_validator(mode="after")
    def check_email_matches_type(self) -> "CreateInviteRequest":
        if self.type is InviteType.DIRECT and self.email is None:
            raise ValueError("email is required for a direct invite")
        if self.type is InviteType.PUBLIC and self.email is not None:
            raise ValueError("email must not be provided for a public invite")
        return self
