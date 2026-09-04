from datetime import UTC, datetime
from typing import Annotated, ClassVar

import shortuuid
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import ASCENDING, IndexModel

from canterlot.emails import EmailCategory
from canterlot.types import (
    AuthProviderName,
    AvatarSchema,
    BadgeReason,
    EarnedBadgeSchema,
    HttpsUrl,
    NormalizedEmailStr,
    PersonNameStr,
    UsernameStr,
)

from .book import ReadBook


class LinkedProviderSchema(BaseModel):
    provider: AuthProviderName
    external_id: str
    picture_url: HttpsUrl | None = None
    linked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EmailPreferencesSchema(BaseModel):
    verified_at: datetime | None = None
    delivery_failed: bool = False
    categories_opt_out: dict[EmailCategory, datetime] = Field(default_factory=dict)
    categories_system_suppressed: dict[EmailCategory, datetime] = Field(default_factory=dict)
    clubs_opt_out: dict[PydanticObjectId, datetime] = Field(default_factory=dict)


class UserModel(Document):
    name: PersonNameStr
    username: Annotated[UsernameStr, Indexed(unique=True)]
    email: Annotated[NormalizedEmailStr, Indexed(unique=True)]
    hashed_password: str | None = None
    linked_providers: list[LinkedProviderSchema] = Field(default_factory=list)
    avatar: AvatarSchema | None = None
    generated_avatar_seed: str = Field(default_factory=shortuuid.random)
    referral_count: int = Field(default=0)
    badges: list[EarnedBadgeSchema] = Field(default_factory=lambda: [EarnedBadgeSchema(reason=BadgeReason.JOINED)])
    refresh_tokens: list[str] = Field(default_factory=list)
    books_read: list[ReadBook] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    accepted_terms_version: int | None = None
    accepted_terms_at: datetime | None = None
    accepted_privacy_version: int | None = None
    accepted_privacy_at: datetime | None = None
    profile_completed_at: datetime | None = None
    email_preferences: EmailPreferencesSchema = Field(default_factory=EmailPreferencesSchema)
    last_seen_at: datetime | None = None

    class Settings:
        name = "users"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [("linked_providers.provider", ASCENDING), ("linked_providers.external_id", ASCENDING)],
                unique=True,
                name="unique_linked_provider_identity",
                # An empty linked_providers array still produces one index entry with both
                # fields null (Mongo's multikey behavior for an empty array), so without this
                # filter every password-only account would collide on that single null entry.
                # partialFilterExpression only supports a small operator set (no $ne), so
                # "array is non-empty" is expressed as "index 0 exists" instead.
                partialFilterExpression={"linked_providers.0": {"$exists": True}},
            )
        ]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()

    @model_validator(mode="after")
    def verify_unique_linked_providers(self):
        providers = [linked.provider for linked in self.linked_providers]

        if len(providers) != len(set(providers)):
            raise ValueError("The same provider credential cannot be linked twice on one account.")

        return self
