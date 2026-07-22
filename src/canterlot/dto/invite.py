from pydantic import BaseModel, model_validator

from canterlot.types import (
    ClubNameStr,
    ClubSlugStr,
    InviteType,
    JoinPolicy,
    NormalizedEmailStr,
    UsernameStr,
)


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
    username: UsernameStr | None = None

    @model_validator(mode="after")
    def check_email_matches_type(self) -> "CreateInviteRequest":
        if self.type is InviteType.PUBLIC and (self.email or self.username):
            raise ValueError("email and username must not be provided for a public invite")

        if self.type is InviteType.DIRECT and bool(self.email) == bool(self.username):
            raise ValueError("a direct invite requires either an email or a username, but not both")

        return self
