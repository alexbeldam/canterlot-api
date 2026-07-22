import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from beanie import PydanticObjectId
from pydantic import (
    AfterValidator,
    BeforeValidator,
    EmailStr,
    Field,
    GetCoreSchemaHandler,
    HttpUrl,
    SecretStr,
    StringConstraints,
    TypeAdapter,
    UrlConstraints,
)
from pydantic.main import BaseModel
from pydantic_core import CoreSchema, PydanticCustomError, core_schema

from canterlot.utils.format import ISBN10_LEN, ISBN13_LEN, make_uppercase, normalize_email, normalize_isbn
from canterlot.utils.language import normalize_language

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 64
MIN_PUBLISHED_YEAR = 868  # Diamond Sutra publication date
MAX_YEAR_OFFSET = 2


# === 1. Enums ===
class JoinPolicy(StrEnum):
    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    RESET = "reset"


class InviteType(StrEnum):
    PUBLIC = "PUBLIC"
    DIRECT = "DIRECT"


class SessionType(StrEnum):
    PASSWORD = "PASSWORD"
    OAUTH = "OAUTH"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ClubOnboardingStatus(StrEnum):
    JOINED = "JOINED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    BANNED = "BANNED"


class AuthProviderName(StrEnum):
    GOOGLE = "GOOGLE"
    GRAVATAR = "GRAVATAR"


class BadgeReason(StrEnum):
    JOINED = "JOINED"


class AuthOutcome(StrEnum):
    LOGGED_IN = "LOGGED_IN"
    CREATED = "CREATED"


class ExtensionType(StrEnum):
    PDF = "pdf"
    EPUB = "epub"


class BookProviderName(StrEnum):
    GOOGLE = "google-books"


class LinkProviderName(StrEnum):
    ANNAS = "annas-archive"


class VerificationScope(StrEnum):
    PASSWORD_RESET = "password"
    EMAIL = "email"

    @property
    def ttl_minutes(self) -> int:
        from canterlot.config import get_settings

        settings = get_settings().auth

        match self:
            case VerificationScope.PASSWORD_RESET:
                return settings.verification_password_reset_ttl_minutes
            case VerificationScope.EMAIL:
                return settings.verification_email_ttl_minutes


# === 2. Base & Domain Types ===
def _validate_secret_verification_code(v: object) -> SecretStr:
    raw_val = v.get_secret_value() if isinstance(v, SecretStr) else v

    validated_str = _code_adapter.validate_python(raw_val)

    return SecretStr(validated_str)


def _validate_password(v: str | SecretStr) -> str:
    password = v.strip() if isinstance(v, str) else v.get_secret_value().strip()

    if len(password) < MIN_PASSWORD_LENGTH:
        raise PydanticCustomError(
            "password_too_short",
            "Password must be at least {min_length} characters long",
            {"min_length": MIN_PASSWORD_LENGTH},
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PydanticCustomError(
            "password_too_long",
            "Password must be at most {max_length} characters long",
            {"max_length": MAX_PASSWORD_LENGTH},
        )
    if not re.search(r"[a-z]", password):
        raise PydanticCustomError(
            "password_missing_lowercase",
            "Password must contain a lowercase letter",
        )
    if not re.search(r"[A-Z]", password):
        raise PydanticCustomError(
            "password_missing_uppercase",
            "Password must contain an uppercase letter",
        )
    if not re.search(r"\d", password):
        raise PydanticCustomError(
            "password_missing_digit",
            "Password must contain a digit",
        )
    if password.isalnum():
        raise PydanticCustomError(
            "password_missing_special_char",
            "Password must contain a special character",
        )

    return password


def _validate_published_year(v: int) -> int:
    max_allowed_year = datetime.now().year + MAX_YEAR_OFFSET

    if v < MIN_PUBLISHED_YEAR:
        raise PydanticCustomError(
            "too_small",
            "Year cannot be earlier than {min_year}",
            {"min_year": MIN_PUBLISHED_YEAR},
        )
    if v > max_allowed_year:
        raise PydanticCustomError(
            "too_large",
            "Year cannot be further in the future than {max_year}",
            {"max_year": max_allowed_year},
        )

    return v


class MemberSchema(BaseModel):
    user_id: PydanticObjectId
    role: MemberRole = MemberRole.MEMBER
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BookProviderIdentifier:
    def __init__(self, provider: BookProviderName, book_id: str):
        self.provider = provider
        self.book_id = book_id

    def __repr__(self) -> str:
        return f"BookProviderIdentifier(provider='{self.provider}', id='{self.book_id}')"

    def __str__(self) -> str:
        return f"{self.provider}__{self.book_id}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BookProviderIdentifier):
            return NotImplemented
        return self.provider == other.provider and self.book_id == other.book_id

    def __hash__(self) -> int:
        return hash((self.provider, self.book_id))

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        def validate(value: Any) -> BookProviderIdentifier:
            if isinstance(value, cls):
                return value
            if isinstance(value, str):
                if "__" not in value:
                    raise PydanticCustomError(
                        "invalid_identifier_format",
                        "Identifier must follow the 'provider__id' format",
                    )
                provider, provider_book_id = value.split("__", 1)
                if not provider or not provider_book_id:
                    raise PydanticCustomError(
                        "empty_identifier_segment",
                        "Both provider and id segments must be non-empty strings",
                    )
                try:
                    provider_name = BookProviderName(provider)
                except ValueError:
                    raise PydanticCustomError(
                        "invalid_provider_name",
                        "Provider segment must be a valid name",
                    ) from None
                return cls(provider_name, provider_book_id)
            raise PydanticCustomError(
                "invalid_identifier_type",
                "Input must be a string or an instance of ProviderIdentifier",
            )

        def serialize(instance: BookProviderIdentifier) -> str:
            return str(instance)

        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_plain_validator_function(
                validate, json_schema_input_schema=core_schema.str_schema()
            ),
            python_schema=core_schema.no_info_plain_validator_function(validate),
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, return_schema=core_schema.str_schema()
            ),
        )


class AvatarSchema(BaseModel):
    source: AuthProviderName
    value: "HttpsUrl"


class EarnedBadgeSchema(BaseModel):
    reason: BadgeReason
    earned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


type ClubNameStr = Annotated[
    NonEmptyStr,
    StringConstraints(min_length=3, max_length=50),
    Field(examples=["The Canterlot Archives", "Manehattan Literature Society"]),
]
type ClubSlugStr = Annotated[
    NonEmptyStr,
    StringConstraints(max_length=32),
    Field(
        examples=[
            "the-canterlot-archives",
            "manehattan-literature-society",
        ]
    ),
]
type HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]
type NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type NormalizedEmailStr = Annotated[EmailStr, BeforeValidator(normalize_email)]
type VerificationCodeStr = Annotated[
    str,
    BeforeValidator(make_uppercase),
    StringConstraints(min_length=8, max_length=8, pattern=r"^[0-9]+$"),
]
type LanguageStr = Annotated[str, AfterValidator(normalize_language), Field(examples=["en", "pt-BR"])]
type TitleStr = Annotated[
    NonEmptyStr,
    StringConstraints(max_length=200),
    Field(examples=["The Hobbit", "A Game of Thrones"]),
]
type UrlList = Annotated[
    dict[ExtensionType, HttpsUrl],
    Field(
        json_schema_extra={
            "examples": [
                {
                    "pdf": "https://example.com/book.pdf",
                    "epub": "https://example.com/book.epub",
                }
            ]
        }
    ),
]
type PublishedYear = Annotated[
    int,
    AfterValidator(_validate_published_year),
    Field(examples=[1998, 2025]),
]
type AuthorList = Annotated[
    list[NonEmptyStr],
    Field(
        examples=[
            ["J.R.R. Tolkien"],
            ["George R.R. Martin", "Fire & Blood Editorial Team"],
        ],
    ),
]
type PageCount = Annotated[int, Field(ge=0, examples=[310, 700])]
type SecretVerificationCode = Annotated[
    SecretStr,
    BeforeValidator(_validate_secret_verification_code),
]
type PasswordStr = Annotated[SecretStr, BeforeValidator(_validate_password)]
type BookExternalId = Annotated[
    BookProviderIdentifier,
    Field(
        description=(
            "The unique, URL-safe external identifier combining the source provider name "
            "and their asset ID, separated by a double underscore. Format: 'provider__id'."
        ),
        examples=["google-books__zyTCAlFlgZ8C"],
    ),
]
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

_code_adapter: TypeAdapter[VerificationCodeStr] = TypeAdapter(VerificationCodeStr)
secret_code_adapter: TypeAdapter[SecretVerificationCode] = TypeAdapter(SecretVerificationCode)


# === 3. ISBN Types ===
type ISBNStr = Annotated[str, BeforeValidator(normalize_isbn), Field(examples=["123456789X"])]
type ISBN10Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN10_LEN, max_length=ISBN10_LEN)]
type ISBN13Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN13_LEN, max_length=ISBN13_LEN)]


# === 4. Annotated Enum Types ===
def _validate_and_format_role(v: Any) -> str:
    val = v.value if isinstance(v, MemberRole) else str(v).upper()

    try:
        return MemberRole(val).value.title()
    except ValueError:
        raise PydanticCustomError(
            "invalid_member_role",
            "'{input_role}' is not a valid member role",
            {"input_role": str(v)},
        ) from None


def _validate_and_format_provider(v: Any) -> str:
    val = v.value if isinstance(v, AuthProviderName) else str(v).upper()

    try:
        return AuthProviderName(val).value.title()
    except ValueError:
        raise PydanticCustomError(
            "invalid_auth_provider",
            "'{input_provider}' is not a valid authentication provider",
            {"input_provider": str(v)},
        ) from None


type TitleCaseMemberRole = Annotated[str, BeforeValidator(_validate_and_format_role)]
type TitleCaseAuthProviderName = Annotated[str, BeforeValidator(_validate_and_format_provider)]
