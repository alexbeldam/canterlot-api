from pydantic import BaseModel

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


class DirectInvitePayload(BaseModel):
    email: NormalizedEmailStr
