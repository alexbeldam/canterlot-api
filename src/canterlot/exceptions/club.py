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
