from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from canterlot.dto.club import ClubOnboarding
from canterlot.models.user import UserModel
from canterlot.types import (
    AuthProviderName,
    NormalizedEmailStr,
    PasswordStr,
    PersonNameStr,
    SecretVerificationCode,
    SessionType,
    UsernameStr,
)


class UserRegisterRequest(BaseModel):
    name: PersonNameStr
    username: UsernameStr
    email: NormalizedEmailStr
    password: PasswordStr
    terms_version: int = Field(..., description="The `**Version:** N` of the Terms of Service being accepted.")
    privacy_version: int = Field(..., description="The `**Version:** N` of the Privacy Policy being accepted.")
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
    password: SecretStr | None = None
    provider: AuthProviderName | None = None
    credential: str | None = Field(
        default=None,
        description="The provider's opaque proof-of-ownership token (e.g. a Google ID token).",
    )
    invite_id: str | None = Field(
        default=None,
        description=(
            "An invitation token this OAuth sign-in arrived from. When it resolves and this sign-in creates a "
            "new account, the inviter is credited with a referral -- this does not join the club itself, which "
            "still requires the existing PATCH /invites/{invite_id} once authenticated."
        ),
    )
    invited_by: UsernameStr | None = Field(
        default=None,
        description="Fallback inviter username for a public link invite whose creator can't be resolved directly.",
    )

    @model_validator(mode="after")
    def validate_session_type_fields(self) -> "CreateSessionRequest":
        if self.type is SessionType.PASSWORD:
            self.__validate_password_fields()
        elif self.type is SessionType.OAUTH:
            self.__validate_oauth_fields()

        return self

    def __validate_password_fields(self) -> None:
        if self.username is None or self.password is None:
            raise ValueError("username and password are required for a PASSWORD session")
        if any(x is not None for x in (self.provider, self.credential, self.invite_id, self.invited_by)):
            raise ValueError("OAuth fields and invite tokens must not be provided for a PASSWORD session")

    def __validate_oauth_fields(self) -> None:
        if self.provider is None or self.credential is None:
            raise ValueError("provider and credential are required for an OAUTH session")
        if self.username is not None or self.password is not None:
            raise ValueError("username and password must not be provided for an OAUTH session")


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


class RequestPasswordResetRequest(BaseModel):
    identifier: NormalizedEmailStr | UsernameStr


class ValidatePasswordResetCodeRequest(BaseModel):
    token: str | None = None
    identifier: NormalizedEmailStr | UsernameStr | None = None
    code: SecretVerificationCode | None = None

    @model_validator(mode="after")
    def validate_xor_inputs(self) -> Self:
        has_token = self.token is not None
        has_direct_credentials = self.identifier is not None and self.code is not None

        # Partial direct payload check
        if (self.identifier is not None or self.code is not None) and not has_direct_credentials:
            raise ValueError("Both 'identifier' and 'code' must be provided together.")

        # Strict XOR: strictly token OR direct credentials, never both and never neither
        if has_token == has_direct_credentials:
            raise ValueError("You must provide either 'token' or both 'identifier' and 'code', but not both.")

        return self


class ResetPasswordRequest(BaseModel):
    new_password: PasswordStr


class ResetSessionStatusResponse(BaseModel):
    is_creation: bool = Field(
        description=(
            "True if the account currently has no password set "
            "(OAuth-only account setting a password for the first time)."
        )
    )


class ConfirmEmailVerificationRequest(BaseModel):
    token: str | None = Field(
        default=None,
        description="Signed action link token from the verification email.",
    )
    code: SecretVerificationCode | None = Field(
        default=None,
        description="6-digit code entered manually in the app.",
    )

    @model_validator(mode="after")
    def validate_xor_inputs(self) -> Self:
        has_token = bool(self.token)
        has_code = bool(self.code)

        if not (has_token ^ has_code):
            raise ValueError("Must provide either 'token' or 'code', but not both.")
        return self
