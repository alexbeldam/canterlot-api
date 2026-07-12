from fastapi import status

from .base import BusinessError, ErrorCode


class ClubDomainError(BusinessError):
    pass


class ClubNotFoundError(ClubDomainError):
    error_code = ErrorCode.CLUB_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND


class ClubSuggestionsClosedError(ClubDomainError):
    error_code = ErrorCode.CLUB_SUGGESTIONS_CLOSED
    status_code = status.HTTP_403_FORBIDDEN


class UnauthorizedClubMemberError(ClubDomainError):
    error_code = ErrorCode.UNAUTHORIZED_CLUB_MEMBER
    status_code = status.HTTP_403_FORBIDDEN


class PendingRequestNotFoundError(ClubDomainError):
    error_code = ErrorCode.PENDING_REQUEST_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND


class ClubMemberNotFoundError(ClubDomainError):
    error_code = ErrorCode.CLUB_MEMBER_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND


class CannotTransferOwnershipToSelfError(ClubDomainError):
    error_code = ErrorCode.CANNOT_TRANSFER_OWNERSHIP_TO_SELF
    status_code = status.HTTP_400_BAD_REQUEST


class OwnershipTransferCooldownError(ClubDomainError):
    error_code = ErrorCode.OWNERSHIP_TRANSFER_COOLDOWN
    status_code = status.HTTP_409_CONFLICT


class OwnershipReclaimWindowExpiredError(ClubDomainError):
    error_code = ErrorCode.OWNERSHIP_RECLAIM_WINDOW_EXPIRED
    status_code = status.HTTP_409_CONFLICT


class OwnershipTransferConflictError(ClubDomainError):
    error_code = ErrorCode.OWNERSHIP_TRANSFER_CONFLICT
    status_code = status.HTTP_409_CONFLICT


class FormerOwnerProtectedError(ClubDomainError):
    error_code = ErrorCode.FORMER_OWNER_PROTECTED
    status_code = status.HTTP_409_CONFLICT
