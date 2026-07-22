from beanie import Document

from .book import BookModel, LinkCandidate
from .club import CatalogEntryModel, ClubModel, MemberSchema, PendingApprovalSchema
from .error import ErrorCode, ErrorDetail, ErrorResponseModel
from .invite import InviteModel
from .user import AvatarSchema, LinkedProviderSchema, UserModel
from .verification import VerificationCodeModel

BEANIE_DOCUMENT_MODELS: list[type[Document]] = [
    BookModel,
    ClubModel,
    InviteModel,
    UserModel,
    VerificationCodeModel,
]

__all__ = [
    "BEANIE_DOCUMENT_MODELS",
    "AvatarSchema",
    "BookModel",
    "CatalogEntryModel",
    "ClubModel",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponseModel",
    "InviteModel",
    "LinkCandidate",
    "LinkedProviderSchema",
    "MemberSchema",
    "PendingApprovalSchema",
    "UserModel",
    "VerificationCodeModel",
]
