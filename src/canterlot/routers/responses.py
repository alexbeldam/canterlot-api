from typing import Any

from fastapi import status

from canterlot.dto.auth import ResetSessionStatusResponse
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    BookDetailsNotFoundError,
    BookNotFoundError,
    BookProviderUnavailableError,
    BookSearchCriteriaMissingError,
    CannotChangeOwnerRoleError,
    CannotTransferOwnershipToSelfError,
    ClubMemberNotFoundError,
    ClubNotFoundError,
    ClubOwnerCannotLeaveError,
    ClubSuggestionsClosedError,
    CodeExpiredError,
    DirectInviteIdentityMismatchError,
    EmailAlreadyExistsError,
    FormerOwnerProtectedError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidCodeError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InvalidOAuthCredentialError,
    InviteLinkDeactivatedError,
    LastAuthenticationMethodError,
    MemberBannedError,
    MemberRoleChangeConflictError,
    OAuthAccountCreationConflictError,
    OAuthLinkRequiredError,
    OwnershipReclaimWindowExpiredError,
    OwnershipTransferConflictError,
    OwnershipTransferCooldownError,
    PasswordAlreadySetError,
    PasswordNotSetError,
    PendingRequestNotFoundError,
    RateLimitExceededError,
    SamePasswordError,
    StaleLegalVersionError,
    TokenExpiredError,
    TokenMalformedError,
    UnauthorizedClubMemberError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from canterlot.exceptions.auth import InvalidUnsubscribePayloadError, UnauthenticatedCodeVerificationError
from canterlot.exceptions.user import EmailAlreadyVerifiedError
from canterlot.models import ErrorResponseModel
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example

type ResponseDict = dict[int | str, dict[str, Any]]

# ==============================================================================
# --- COMMON REUSABLE RESPONSES ---
# ==============================================================================

RESP_400_MALFORMED_TOKEN: ResponseDict = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
        "content": error_example(TokenMalformedError),
    }
}

RESP_401_AUTH: ResponseDict = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": (
            "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired."
        ),
        "content": error_example(InvalidCredentialsError, TokenExpiredError),
    }
}

RESP_500_INTERNAL: ResponseDict = {
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponseModel,
        "description": "Unexpected global backend execution failure or persistence error.",
        "content": INTERNAL_SERVER_ERROR_EXAMPLE,
    }
}

STANDARD_PROTECTED_RESPONSES: ResponseDict = {
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- AUTH ROUTER RESPONSES ---
# ==============================================================================

CREATE_SESSION_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {
        "description": (
            "Session created (password login, or an OAuth credential matched an existing linked account). "
            "Access token returned in the body; the refresh token is set as an httpOnly session cookie."
        )
    },
    status.HTTP_201_CREATED: {
        "description": (
            "OAuth credential verified and a new user account was created from this identity. Access token "
            "returned in the body; the refresh token is set as an httpOnly session cookie."
        )
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": (
            "InvalidCredentialsError: Incorrect username/password combination. "
            "InvalidOAuthCredentialError: The provided OAuth credential failed cryptographic verification."
        ),
        "content": error_example(InvalidCredentialsError, InvalidOAuthCredentialError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": (
            "OAuthAccountCreationConflictError: A concurrent sign-in for this same identity left this "
            "request unable to resolve to an account. Extremely rare; retrying the request resolves it. "
            "OAuthLinkRequiredError: The OAuth credential's identity resolves to an account that already "
            "exists under a different authentication method -- the frontend should prompt the user to log "
            "in with that method and link this provider from there."
        ),
        "content": error_example(OAuthAccountCreationConflictError, OAuthLinkRequiredError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": (
            "Validation error. Fields don't match `type` (PASSWORD requires username+password, OAUTH "
            "requires provider+credential), or `provider` is not a recognized authentication provider."
        )
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": (
            "RateLimitExceededError: Too many sign-in attempts, either from this IP address or "
            "against this account (PASSWORD sessions only -- OAUTH is limited by IP alone)."
        ),
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponseModel,
        "description": "GatewayConfigurationError: This authentication provider is not currently configured.",
        "content": error_example(GatewayConfigurationError),
    },
}

ROTATE_SESSION_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {
        "description": (
            "Session rotated successfully. Old session invalidated; a new access token is returned in the "
            "body and a new refresh cookie is set."
        )
    },
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many session-refresh attempts from this IP address.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

LOGOUT_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {
        "description": (
            "Current session logged out and its refresh cookie cleared. Also returned, as a no-op, when "
            "there was no active session to end."
        )
    },
    **RESP_500_INTERNAL,
}

REQUEST_PASSWORD_RESET_RESPONSES: ResponseDict = {
    status.HTTP_202_ACCEPTED: {
        "description": (
            "Password reset request accepted. If an account with the given identifier exists, "
            "a verification code email has been queued."
        )
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on identifier field."},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many password reset requests from this IP address.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

VALIDATE_PASSWORD_RESET_CODE_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {
        "description": (
            "Verification code successfully validated. A password_reset httpOnly cookie "
            "has been issued for resetting the password."
        )
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError, InvalidCodeError, or CodeExpiredError.",
        "content": error_example(TokenMalformedError, InvalidCodeError, CodeExpiredError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "UserNotFoundError: The user matching this code or token no longer exists.",
        "content": error_example(UserNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "Validation error. Must provide either token or both identifier and code (XOR)."
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many code validation attempts.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

RESET_PASSWORD_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {
        "description": (
            "Password reset successfully. Password reset cookie cleared, fresh refresh_token cookie set, "
            "and access token returned in response body."
        )
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError: Password reset token is corrupt or invalid.",
        "content": error_example(TokenMalformedError),
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": "InvalidCredentialsError or TokenExpiredError: Reset cookie missing or expired.",
        "content": error_example(InvalidCredentialsError, TokenExpiredError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on new_password constraints."},
    **RESP_500_INTERNAL,
}

GET_RESET_SESSION_STATUS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {
        "model": ResetSessionStatusResponse,
        "description": (
            "Active password reset session verified. Returns context flags (e.g. is_creation) "
            "to help the frontend render appropriate form copy."
        ),
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": "InvalidCredentialsError or TokenExpiredError: Reset cookie is missing, corrupt, or expired.",
        "content": error_example(InvalidCredentialsError, TokenExpiredError),
    },
    **RESP_500_INTERNAL,
}

REQUEST_EMAIL_VERIFICATION_RESPONSES: ResponseDict = {
    status.HTTP_202_ACCEPTED: {
        "description": "Verification email queued for delivery.",
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": "Unauthenticated access token.",
        "content": error_example(InvalidCredentialsError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "EmailAlreadyVerifiedError: The email is already verified.",
        "content": error_example(EmailAlreadyVerifiedError),
    },
    **RESP_500_INTERNAL,
}

CONFIRM_EMAIL_VERIFICATION_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {
        "description": "Email verified successfully.",
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "InvalidCodeError or TokenMalformedError.",
        "content": error_example(InvalidCodeError, TokenMalformedError),
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthenticatedCodeVerificationError: Code supplied without an active login session.",
        "content": error_example(UnauthenticatedCodeVerificationError),
    },
    status.HTTP_410_GONE: {
        "model": ErrorResponseModel,
        "description": "CodeExpiredError: Verification code has expired.",
        "content": error_example(CodeExpiredError),
    },
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- BOOKS ROUTER RESPONSES ---
# ==============================================================================

GET_EXTERNAL_BOOK_DETAILS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Successfully retrieved specific external book details."},
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "BookDetailsNotFoundError: Active provider engine not found or volume does not exist.",
        "content": error_example(BookDetailsNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on external identifier structure."},
    **RESP_500_INTERNAL,
    status.HTTP_502_BAD_GATEWAY: {
        "model": ErrorResponseModel,
        "description": "BookProviderUnavailableError: The external provider encountered an upstream error.",
        "content": error_example(BookProviderUnavailableError),
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponseModel,
        "description": "GatewayConfigurationError: External books provider is not configured.",
        "content": error_example(GatewayConfigurationError),
    },
}

SEARCH_EXTERNAL_BOOKS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Successfully retrieved paginated list of external books matching criteria."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "BookSearchCriteriaMissingError: None of title, author, or isbn were provided.",
        "content": error_example(BookSearchCriteriaMissingError),
    },
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: The requesting user is not a member of club_slug.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given club_slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on query params."},
    **RESP_500_INTERNAL,
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponseModel,
        "description": "GatewayConfigurationError: External books provider is not configured.",
        "content": error_example(GatewayConfigurationError),
    },
}

GET_BOOK_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Successfully retrieved internal book record."},
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "BookNotFoundError: No book matches the given identifier.",
        "content": error_example(BookNotFoundError),
    },
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- CATALOG ROUTER RESPONSES ---
# ==============================================================================

SUGGEST_BOOK_RESPONSES: ResponseDict = {
    status.HTTP_201_CREATED: {"description": "Book suggestion newly added to the club catalog."},
    status.HTTP_200_OK: {"description": "This book already exists in the club's catalog; existing entry returned."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError or ClubSuggestionsClosedError.",
        "content": error_example(UnauthorizedClubMemberError, ClubSuggestionsClosedError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on club_id or body payload."},
    **RESP_500_INTERNAL,
}

GET_CLUB_CATALOG_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Successfully retrieved a paginated page of the club's catalog."},
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: The requesting user is not a member of this club.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on path or query params."},
    **RESP_500_INTERNAL,
}

REMOVE_FROM_CLUB_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Book successfully removed from the club catalog."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Lacks permissions to remove this book.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError or BookNotFoundError.",
        "content": error_example(ClubNotFoundError, BookNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on path parameter."},
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- CLUBS ROUTER RESPONSES ---
# ==============================================================================

CREATE_CLUB_RESPONSES: ResponseDict = {
    status.HTTP_201_CREATED: {"description": "Club workspace initialized successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Creator's ownership status could not be verified.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on request body constraints."},
    **RESP_500_INTERNAL,
}

UPDATE_CLUB_SETTINGS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "The club's settings were updated successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold OWNER/ADMIN standing.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on settings fields."},
    **RESP_500_INTERNAL,
}

GET_CLUB_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Club metadata retrieved."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Requesting user is not a member of this club.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given slug.",
        "content": error_example(ClubNotFoundError),
    },
    **RESP_500_INTERNAL,
}

DISSOLVE_CLUB_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Club dissolved."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold OWNER standing.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "FormerOwnerProtectedError: Former owner still protected from removal.",
        "content": error_example(FormerOwnerProtectedError),
    },
    **RESP_500_INTERNAL,
}

REVIEW_PENDING_REQUEST_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Join request state updated."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold OWNER or ADMIN standing.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError, UserNotFoundError, or PendingRequestNotFoundError.",
        "content": error_example(ClubNotFoundError, UserNotFoundError, PendingRequestNotFoundError),
    },
    **RESP_500_INTERNAL,
}

CREATE_INVITE_RESPONSES: ResponseDict = {
    status.HTTP_201_CREATED: {"description": "Invite created."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Requesting user lacks Administrative or Owner permissions.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on payload."},
    **RESP_500_INTERNAL,
}

LEAVE_CLUB_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Caller left the club voluntarily."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller is not a member of this club.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "ClubOwnerCannotLeaveError or FormerOwnerProtectedError.",
        "content": error_example(ClubOwnerCannotLeaveError, FormerOwnerProtectedError),
    },
    **RESP_500_INTERNAL,
}

GET_CLUB_MEMBER_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Target member's club profile retrieved."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller is not a member of this club.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError, UserNotFoundError, or ClubMemberNotFoundError.",
        "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
    },
    **RESP_500_INTERNAL,
}

REMOVE_CLUB_MEMBER_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Member removed and banned from the club."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold sufficient rank.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError, UserNotFoundError, or ClubMemberNotFoundError.",
        "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "FormerOwnerProtectedError: Target is still protected from removal.",
        "content": error_example(FormerOwnerProtectedError),
    },
    **RESP_500_INTERNAL,
}

CHANGE_CLUB_MEMBER_ROLE_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Member role updated successfully."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError or CannotChangeOwnerRoleError.",
        "content": error_example(TokenMalformedError, CannotChangeOwnerRoleError),
    },
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold OWNER standing.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError, UserNotFoundError, or ClubMemberNotFoundError.",
        "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "FormerOwnerProtectedError or MemberRoleChangeConflictError.",
        "content": error_example(FormerOwnerProtectedError, MemberRoleChangeConflictError),
    },
    **RESP_500_INTERNAL,
}

CREATE_OWNERSHIP_TRANSFER_RESPONSES: ResponseDict = {
    status.HTTP_201_CREATED: {"description": "Ownership transferred successfully."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError or CannotTransferOwnershipToSelfError.",
        "content": error_example(TokenMalformedError, CannotTransferOwnershipToSelfError),
    },
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller does not hold OWNER standing.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError, UserNotFoundError, or ClubMemberNotFoundError.",
        "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "OwnershipTransferCooldownError or OwnershipTransferConflictError.",
        "content": error_example(OwnershipTransferCooldownError, OwnershipTransferConflictError),
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many ownership actions.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

RECLAIM_CLUB_OWNERSHIP_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Transfer reversed successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "UnauthorizedClubMemberError: Caller is not recorded former owner.",
        "content": error_example(UnauthorizedClubMemberError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with the given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "OwnershipReclaimWindowExpiredError or OwnershipTransferConflictError.",
        "content": error_example(OwnershipReclaimWindowExpiredError, OwnershipTransferConflictError),
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many ownership actions.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

GET_PUBLIC_INVITE_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Active public invite token returned."},
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: No club exists with given slug.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_410_GONE: {
        "model": ErrorResponseModel,
        "description": "InviteLinkDeactivatedError: Club has no active public invite link.",
        "content": error_example(InviteLinkDeactivatedError),
    },
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- INVITES ROUTER RESPONSES ---
# ==============================================================================

PREVIEW_INVITATION_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Invite metadata returned for viewer."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "InvalidInviteTokenError: Invalid invite_id.",
        "content": error_example(InvalidInviteTokenError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: The club no longer exists.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_410_GONE: {
        "model": ErrorResponseModel,
        "description": "InviteLinkDeactivatedError: Invitation deactivated or expired.",
        "content": error_example(InviteLinkDeactivatedError),
    },
    **RESP_500_INTERNAL,
}

ACCEPT_INVITATION_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Invitation accepted; caller joined outright."},
    status.HTTP_202_ACCEPTED: {"description": "Invitation accepted; queued for approval."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError or InvalidInviteTokenError.",
        "content": error_example(TokenMalformedError, InvalidInviteTokenError),
    },
    **RESP_401_AUTH,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "DirectInviteIdentityMismatchError or MemberBannedError.",
        "content": error_example(DirectInviteIdentityMismatchError, MemberBannedError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: The club no longer exists.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_410_GONE: {
        "model": ErrorResponseModel,
        "description": "InviteLinkDeactivatedError: Invitation deactivated or expired.",
        "content": error_example(InviteLinkDeactivatedError),
    },
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- USERS ROUTER RESPONSES ---
# ==============================================================================

REGISTER_RESPONSES: ResponseDict = {
    status.HTTP_201_CREATED: {"description": "User account created successfully."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "InvalidInviteTokenError: Provided invite_id invalid.",
        "content": error_example(InvalidInviteTokenError),
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponseModel,
        "description": "DirectInviteIdentityMismatchError: Email mismatch on invite.",
        "content": error_example(DirectInviteIdentityMismatchError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "ClubNotFoundError: Club no longer exists.",
        "content": error_example(ClubNotFoundError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "UsernameAlreadyExistsError, EmailAlreadyExistsError, or StaleLegalVersionError.",
        "content": error_example(UsernameAlreadyExistsError, EmailAlreadyExistsError, StaleLegalVersionError),
    },
    status.HTTP_410_GONE: {
        "model": ErrorResponseModel,
        "description": "InviteLinkDeactivatedError: Invite deactivated or expired.",
        "content": error_example(InviteLinkDeactivatedError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on body."},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponseModel,
        "description": "RateLimitExceededError: Too many registration attempts.",
        "content": error_example(RateLimitExceededError),
    },
    **RESP_500_INTERNAL,
}

GET_OWN_PROFILE_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Caller's own profile returned."},
    **STANDARD_PROTECTED_RESPONSES,
}

UPDATE_PROFILE_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Profile updated successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "UsernameAlreadyExistsError: Username taken.",
        "content": error_example(UsernameAlreadyExistsError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on body fields."},
    **RESP_500_INTERNAL,
}

CHANGE_PASSWORD_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Password changed successfully."},
    **RESP_400_MALFORMED_TOKEN,
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": "InvalidCredentialsError, TokenExpiredError, or IncorrectPasswordError.",
        "content": error_example(InvalidCredentialsError, TokenExpiredError, IncorrectPasswordError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "PasswordNotSetError or SamePasswordError.",
        "content": error_example(PasswordNotSetError, SamePasswordError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error."},
    **RESP_500_INTERNAL,
}

CREATE_PASSWORD_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Password created successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "PasswordAlreadySetError: Password already set on account.",
        "content": error_example(PasswordAlreadySetError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error."},
    **RESP_500_INTERNAL,
}

SET_AVATAR_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Avatar updated successfully."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "AuthProviderNotLinkedError: Source provider not linked.",
        "content": error_example(AuthProviderNotLinkedError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on source."},
    **RESP_500_INTERNAL,
}

CLEAR_AVATAR_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Provider photo cleared; fallback to seed."},
    **STANDARD_PROTECTED_RESPONSES,
}

REGENERATE_AVATAR_SEED_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Avatar seed regenerated."},
    **STANDARD_PROTECTED_RESPONSES,
}

ACCEPT_LEGAL_DOCUMENTS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Legal acceptance recorded."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "StaleLegalVersionError: Legal documents version mismatch.",
        "content": error_example(StaleLegalVersionError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error."},
    **RESP_500_INTERNAL,
}

GET_CONNECTED_PROVIDERS_RESPONSES: ResponseDict = {
    status.HTTP_200_OK: {"description": "Connected authentication methods returned."},
    **STANDARD_PROTECTED_RESPONSES,
}

LINK_PROVIDER_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Provider linked to account."},
    **RESP_400_MALFORMED_TOKEN,
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponseModel,
        "description": "InvalidCredentialsError, TokenExpiredError, or InvalidOAuthCredentialError.",
        "content": error_example(InvalidCredentialsError, TokenExpiredError, InvalidOAuthCredentialError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "AuthProviderAlreadyLinkedError: Provider credential already linked elsewhere.",
        "content": error_example(AuthProviderAlreadyLinkedError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on provider name."},
    **RESP_500_INTERNAL,
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponseModel,
        "description": "GatewayConfigurationError: Provider not configured.",
        "content": error_example(GatewayConfigurationError),
    },
}

DISCONNECT_PROVIDER_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Provider disconnected."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "AuthProviderNotLinkedError: No linked account exists for provider.",
        "content": error_example(AuthProviderNotLinkedError),
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponseModel,
        "description": "LastAuthenticationMethodError: Cannot remove sole sign-in method.",
        "content": error_example(LastAuthenticationMethodError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on provider name."},
    **RESP_500_INTERNAL,
}

MARK_BOOK_READ_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {"description": "Book recorded in reading history."},
    **RESP_400_MALFORMED_TOKEN,
    **RESP_401_AUTH,
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "BookNotFoundError: Identifier doesn't match any known book.",
        "content": error_example(BookNotFoundError),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error on identifier."},
    **RESP_500_INTERNAL,
}

# ==============================================================================
# --- UNSUBSCRIBE ROUTER RESPONSES ---
# ==============================================================================

ONE_CLICK_UNSUBSCRIBE_RESPONSES: ResponseDict = {
    status.HTTP_204_NO_CONTENT: {
        "description": "Unsubscribe request processed successfully via RFC 8058 1-click POST."
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": (
            "InvalidUnsubscribePayloadError or TokenMalformedError: Missing "
            "'List-Unsubscribe=One-Click' body or corrupt token."
        ),
        "content": error_example(InvalidUnsubscribePayloadError, TokenMalformedError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "UserNotFoundError: User associated with this token no longer exists.",
        "content": error_example(UserNotFoundError),
    },
    **RESP_500_INTERNAL,
}

BROWSER_UNSUBSCRIBE_RESPONSES: ResponseDict = {
    status.HTTP_303_SEE_OTHER: {"description": "Unsubscribe processed; redirects user browser to confirmation page."},
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponseModel,
        "description": "TokenMalformedError: Unsubscribe token is corrupt, malformed, or altered.",
        "content": error_example(TokenMalformedError),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponseModel,
        "description": "UserNotFoundError: User associated with this token no longer exists.",
        "content": error_example(UserNotFoundError),
    },
    **RESP_500_INTERNAL,
}
