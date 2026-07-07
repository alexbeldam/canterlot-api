from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from canterlot.utils.format import NonEmptyStr, NormalizedEmailStr

from .book import ReadBook
from .enums import AuthProviderName

type UsernameStr = Annotated[
    NonEmptyStr,
    StringConstraints(min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_]+$"),
    Field(examples=["twilight_sparkle", "bookworm99"]),
]
type PersonNameStr = Annotated[
    NonEmptyStr,
    StringConstraints(min_length=2, max_length=50),
    Field(examples=["Twilight Sparkle", "Alex Smith"]),
]


class LinkedProviderSchema(BaseModel):
    provider: AuthProviderName
    external_id: str
    linked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserModel(Document):
    name: PersonNameStr
    username: Annotated[UsernameStr, Indexed(unique=True)]
    email: Annotated[NormalizedEmailStr, Indexed(unique=True)]
    hashed_password: str | None = None
    linked_providers: list[LinkedProviderSchema] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def verify_unique_linked_providers(self):
        identities = [(linked.provider, linked.external_id) for linked in self.linked_providers]

        if len(identities) != len(set(identities)):
            raise ValueError("The same provider credential cannot be linked twice on one account.")

        return self
