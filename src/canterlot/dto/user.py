from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from canterlot.config import get_settings
from canterlot.models.enums import AuthProviderName, BadgeReason
from canterlot.models.user import AvatarSchema, EarnedBadgeSchema, PersonNameStr, UserModel, UsernameStr
from canterlot.utils.format import HttpsUrl, NormalizedEmailStr


class UpdateProfileRequest(BaseModel):
    name: PersonNameStr | None = None
    username: UsernameStr | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else v

    @model_validator(mode="after")
    def check_at_least_one_field_provided(self) -> "UpdateProfileRequest":
        if self.name is None and self.username is None:
            raise ValueError("At least one of name or username must be provided.")
        return self


class AvatarDTO(BaseModel):
    source: AuthProviderName
    value: HttpsUrl

    @classmethod
    def from_model(cls, avatar: AvatarSchema) -> "AvatarDTO":
        return cls(source=avatar.source, value=avatar.value)


class SetAvatarRequest(BaseModel):
    source: AuthProviderName


class BadgeDTO(BaseModel):
    reason: BadgeReason
    earned_at: datetime
    bonus: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_model(cls, badge: EarnedBadgeSchema) -> "BadgeDTO":
        return cls(reason=badge.reason, earned_at=badge.earned_at)


class UserProfileResponse(BaseModel):
    name: PersonNameStr
    username: UsernameStr
    email: NormalizedEmailStr
    avatar: AvatarDTO | None = None
    generated_avatar_seed: str
    badges: list[BadgeDTO] = Field(default_factory=list)
    needs_profile_completion: bool
    needs_terms_reacceptance: bool
    needs_privacy_reacceptance: bool

    @classmethod
    def from_model(cls, user: UserModel) -> "UserProfileResponse":
        settings = get_settings()
        return cls(
            name=user.name,
            username=user.username,
            email=user.email,
            avatar=AvatarDTO.from_model(user.avatar) if user.avatar else None,
            generated_avatar_seed=user.generated_avatar_seed,
            badges=[BadgeDTO.from_model(badge) for badge in user.badges],
            needs_profile_completion=user.profile_completed_at is None,
            needs_terms_reacceptance=(
                user.accepted_terms_version is None or user.accepted_terms_version < settings.current_terms_version
            ),
            needs_privacy_reacceptance=(
                user.accepted_privacy_version is None
                or user.accepted_privacy_version < settings.current_privacy_version
            ),
        )


class ChangePasswordRequest(BaseModel):
    current_password: str | None = Field(default=None, min_length=6, examples=["old_super_secret_password_456"])
    new_password: str = Field(..., min_length=6, examples=["new_super_secret_password_456"])


class LegalAcceptanceRequest(BaseModel):
    terms_version: int = Field(..., description="The `**Version:** N` of the Terms of Service being accepted.")
    privacy_version: int = Field(..., description="The `**Version:** N` of the Privacy Policy being accepted.")
