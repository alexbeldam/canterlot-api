from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, EmailStr, Field, HttpUrl, StringConstraints
from pydantic.functional_validators import BeforeValidator
from pydantic.networks import UrlConstraints

from canterlot.utils.format import ISBN10_LEN, ISBN13_LEN, make_uppercase, normalize_email, normalize_isbn
from canterlot.utils.language import normalize_language


# === 1. Enums ===
class JoinPolicy(StrEnum):
    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"


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


# === 2. Base & Domain Types ===
type HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]
type NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type NormalizedEmailStr = Annotated[EmailStr, BeforeValidator(normalize_email)]
type VerificationCodeStr = Annotated[
    str,
    BeforeValidator(make_uppercase),
    StringConstraints(min_length=8, max_length=8, pattern=r"^[A-Z0-9]+$"),
]
type LanguageStr = Annotated[str, AfterValidator(normalize_language), Field(examples=["en", "pt-BR"])]

# === 3. ISBN Types ===
type ISBNStr = Annotated[str, BeforeValidator(normalize_isbn), Field(examples=["123456789X"])]
type ISBN10Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN10_LEN, max_length=ISBN10_LEN)]
type ISBN13Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN13_LEN, max_length=ISBN13_LEN)]


# === 4. Annotated Enum Types ===
def _validate_and_format_role(v: Any) -> str:
    val = v.value if isinstance(v, MemberRole) else str(v).upper()

    return MemberRole(val).value.title()


def _validate_and_format_provider(v: Any) -> str:
    val = v.value if isinstance(v, AuthProviderName) else str(v).upper()

    return AuthProviderName(val).value.title()


type TitleCaseMemberRole = Annotated[str, BeforeValidator(_validate_and_format_role)]
type TitleCaseAuthProviderName = Annotated[str, BeforeValidator(_validate_and_format_provider)]
