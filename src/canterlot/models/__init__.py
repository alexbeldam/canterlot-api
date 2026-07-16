from beanie import Document

from .book import BookModel, LinkCandidate
from .club import CatalogEntryModel, ClubModel, MemberSchema, PendingApprovalSchema
from .enums import (
    AuthOutcome,
    AuthProviderName,
    BadgeReason,
    ClubOnboardingStatus,
    InviteType,
    JoinPolicy,
    MemberRole,
)
from .error import ErrorCode, ErrorDetail, ErrorResponseModel
from .invite import InviteModel
from .user import AvatarSchema, LinkedProviderSchema, UserModel

BEANIE_DOCUMENT_MODELS: list[type[Document]] = [BookModel, ClubModel, InviteModel, UserModel]

__all__ = [
    "BEANIE_DOCUMENT_MODELS",
    "AuthOutcome",
    "AuthProviderName",
    "AvatarSchema",
    "BadgeReason",
    "BookModel",
    "CatalogEntryModel",
    "ClubModel",
    "ClubOnboardingStatus",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponseModel",
    "InviteModel",
    "InviteType",
    "JoinPolicy",
    "LinkCandidate",
    "LinkedProviderSchema",
    "MemberRole",
    "MemberSchema",
    "PendingApprovalSchema",
    "UserModel",
]
