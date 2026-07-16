from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from canterlot.dto.club import ClubOnboarding
from canterlot.models.enums import AuthProviderName, SessionType
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
    # Service-internal only -- the refresh token rides an httpOnly cookie, never a response body.
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(AccessTokenResponse):
    onboarding: ClubOnboarding | None = None


class CreateSessionRequest(BaseModel):
    type: SessionType
    username: UsernameStr | None = None
    password: str | None = None
    provider: AuthProviderName | None = None
    credential: str | None = Field(
        default=None,
        description="The provider's opaque proof-of-ownership token (e.g. a Google ID token).",
    )

    @model_validator(mode="after")
    def check_required_fields_present(self) -> "CreateSessionRequest":
        if self.type is SessionType.PASSWORD:
            if self.username is None or self.password is None:
                raise ValueError("username and password are required for a PASSWORD session")
        elif self.provider is None or self.credential is None:
            raise ValueError("provider and credential are required for an OAUTH session")
        return self

    @model_validator(mode="after")
    def check_forbidden_fields_absent(self) -> "CreateSessionRequest":
        if self.type is SessionType.PASSWORD:
            if self.provider is not None or self.credential is not None:
                raise ValueError("provider and credential must not be provided for a PASSWORD session")
        elif self.username is not None or self.password is not None:
            raise ValueError("username and password must not be provided for an OAUTH session")
        return self


class LinkProviderRequest(BaseModel):
    credential: str = Field(
        ...,
        description=(
            "The provider's opaque proof-of-ownership token (e.g. a Google ID token, or a Gravatar authorization code)."
        ),
    )
    redirect_uri: str | None = Field(
        default=None,
        description=(
            "Required only for providers using an authorization-code exchange (e.g. Gravatar), must exactly "
            "match the redirect_uri used in the original authorize request. Ignored by other providers."
        ),
    )


class LinkedProviderDTO(BaseModel):
    provider: AuthProviderName
    linked_at: datetime
    has_picture: bool = Field(
        description="Whether this linked provider carries a profile picture usable as an avatar source."
    )


class ConnectedProvidersResponse(BaseModel):
    has_password: bool
    linked_providers: list[LinkedProviderDTO]

    @classmethod
    def from_model(cls, user: UserModel) -> "ConnectedProvidersResponse":
        return cls(
            has_password=user.hashed_password is not None,
            linked_providers=[
                LinkedProviderDTO(
                    provider=linked.provider,
                    linked_at=linked.linked_at,
                    has_picture=linked.picture_url is not None,
                )
                for linked in user.linked_providers
            ],
        )
