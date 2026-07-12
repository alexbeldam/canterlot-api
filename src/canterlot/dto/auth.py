from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from canterlot.dto.club import ClubOnboarding
from canterlot.models.enums import AuthOutcome, AuthProviderName
from canterlot.models.user import PersonNameStr, UserModel, UsernameStr
from canterlot.utils.format import NormalizedEmailStr


class UserRegisterRequest(BaseModel):
    name: PersonNameStr
    username: UsernameStr
    email: NormalizedEmailStr
    password: str = Field(..., min_length=6, examples=["super_secret_password_123"])
    invite_id: str | None = None
    invited_by: UsernameStr | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterResponse(TokenResponse):
    onboarding: ClubOnboarding | None = None


class OAuthSignInRequest(BaseModel):
    credential: str = Field(
        ...,
        description="The provider's opaque proof-of-ownership token (e.g. a Google ID token).",
    )


class OAuthSignInResponse(BaseModel):
    outcome: AuthOutcome
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"


class LinkProviderRequest(BaseModel):
    credential: str = Field(
        ...,
        description="The provider's opaque proof-of-ownership token (e.g. a Google ID token).",
    )


class LinkedProviderDTO(BaseModel):
    provider: AuthProviderName
    linked_at: datetime


class ConnectedProvidersResponse(BaseModel):
    has_password: bool
    linked_providers: list[LinkedProviderDTO]

    @classmethod
    def from_model(cls, user: UserModel) -> "ConnectedProvidersResponse":
        return cls(
            has_password=user.hashed_password is not None,
            linked_providers=[
                LinkedProviderDTO(provider=linked.provider, linked_at=linked.linked_at)
                for linked in user.linked_providers
            ],
        )
