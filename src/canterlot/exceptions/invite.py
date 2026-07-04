from fastapi import status

from .auth import TokenError
from .base import ErrorCode
from .club import UnauthorizedClubMemberError


class InvalidInviteTokenError(TokenError):
    error_code = ErrorCode.INVALID_INVITE_TOKEN
    status_code = status.HTTP_400_BAD_REQUEST


class InviteLinkDeactivatedError(InvalidInviteTokenError):
    error_code = ErrorCode.INVITE_LINK_DEACTIVATED
    status_code = status.HTTP_410_GONE


class DirectInviteIdentityMismatchError(UnauthorizedClubMemberError):
    error_code = ErrorCode.INVITE_IDENTITY_MISMATCH
    status_code = status.HTTP_403_FORBIDDEN
