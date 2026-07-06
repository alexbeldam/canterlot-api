from enum import StrEnum


class JoinPolicy(StrEnum):
    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"


class InviteType(StrEnum):
    PUBLIC = "PUBLIC"
    DIRECT = "DIRECT"


class UserRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ClubOnboardingStatus(StrEnum):
    JOINED = "JOINED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ALREADY_MEMBER = "ALREADY_MEMBER"


class ExtensionType(StrEnum):
    PDF = "pdf"
    EPUB = "epub"


class BookProviderName(StrEnum):
    GOOGLE = "google-books"


class LinkProviderName(StrEnum):
    ANNAS = "annas-archive"
