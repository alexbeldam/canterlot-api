from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field, StringConstraints, field_validator

from canterlot.utils.format import NonEmptyStr, NormalizedEmailStr

from .book import ReadBook
from .club import ClubOnboarding

type UsernameStr = Annotated[NonEmptyStr, StringConstraints(min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")]
type PersonNameStr = Annotated[NonEmptyStr, StringConstraints(min_length=2, max_length=50)]


class UserModel(Document):
    name: PersonNameStr
    username: Annotated[UsernameStr, Indexed(unique=True)]
    email: Annotated[NormalizedEmailStr, Indexed(unique=True)]
    hashed_password: str
    referral_count: int = Field(default=0)
    refresh_tokens: list[str] = Field(default_factory=list)
    books_read: list[ReadBook] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "users"

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()


class UserRegisterRequest(BaseModel):
    name: PersonNameStr
    username: UsernameStr
    email: NormalizedEmailStr
    password: str = Field(..., min_length=6)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterResult(TokenResponse):
    user_id: PydanticObjectId


class RegisterResponse(TokenResponse):
    onboarding: ClubOnboarding | None = None
