from pydantic import BaseModel, Field, field_validator

from canterlot.dto.club import ClubOnboarding
from canterlot.models.user import PersonNameStr, UsernameStr
from canterlot.utils.format import NormalizedEmailStr


class UserRegisterRequest(BaseModel):
    name: PersonNameStr
    username: UsernameStr
    email: NormalizedEmailStr
    password: str = Field(..., min_length=6, examples=["super_secret_password_123"])

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
