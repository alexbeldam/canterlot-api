from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from canterlot.dto.auth import (
    OAuthSignInRequest,
    OAuthSignInResponse,
    RegisterResponse,
    TokenResponse,
    UserRegisterRequest,
)
from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InvalidOAuthCredentialError,
    InviteLinkDeactivatedError,
    OAuthAccountCreationConflictError,
    TokenExpiredError,
    TokenMalformedError,
    UsernameAlreadyExistsError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.enums import AuthProviderName, ClubOnboardingStatus
from canterlot.models.user import UsernameStr
from canterlot.routers.dependencies import (
    RefreshTokenContext,
    get_auth_service,
    get_club_service,
    get_invite_service,
    get_user_id_from_valid_refresh_token,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import AuthService, ClubService, InviteService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "User account created successfully. Active access and refresh session tokens returned."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidInviteTokenError: The provided invite_id does not correspond to an existing invitation."
            ),
            "content": error_example(InvalidInviteTokenError),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": (
                "DirectInviteIdentityMismatchError: The provided invite_id is a direct invitation bound to a "
                "different email address than the one being registered."
            ),
            "content": error_example(DirectInviteIdentityMismatchError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: The club associated with the provided invite_id no longer exists.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "UsernameAlreadyExistsError or EmailAlreadyExistsError: The username or email string "
                "is already bound to a different profile."
            ),
            "content": error_example(UsernameAlreadyExistsError, EmailAlreadyExistsError),
        },
        status.HTTP_410_GONE: {
            "model": ErrorResponseModel,
            "description": (
                "InviteLinkDeactivatedError: The provided invite_id has been deactivated, rotated, or has expired."
            ),
            "content": error_example(InviteLinkDeactivatedError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Validation error. Request body values violate type constraints or payload formatting requirements."
            )
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected global backend execution failure or persistence error.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def register(
    payload: UserRegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
    invite_id: str | None = None,
    invited_by: UsernameStr | None = None,
):
    validated_invite = None
    inviter_username = invited_by

    if invite_id:
        validated_invite = await invite_service.validate_incoming_invite(
            invite_id,
            payload.email,
            invited_by,
        )

        inviter_username = validated_invite.invited_by or invited_by

    res = await auth_service.register_user(payload, inviter_username)
    onboarding = None

    if validated_invite:
        onboarding = await club_service.admit_user(
            validated_invite.club_id,
            res.user_id,
            validated_invite.is_direct,
        )

        if (
            onboarding
            and onboarding.status in [ClubOnboardingStatus.JOINED, ClubOnboardingStatus.PENDING_APPROVAL]
            and invite_id
        ):
            await invite_service.register_invite_usage(invite_id)

    return RegisterResponse(
        access_token=res.access_token,
        refresh_token=res.refresh_token,
        onboarding=onboarding,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        status.HTTP_200_OK: {"description": "Authentication successful. User credentials verified."},
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError: Incorrect username, profile identity, or plain text password combination."
            ),
            "content": error_example(InvalidCredentialsError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. Form values missing or incorrectly structured during transmission."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected runtime engine error during validation processing.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.login_user(
        username=form_data.username,
        plain_password=form_data.password,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Refresh session token rotated successfully. Old session invalidated and new pair returned."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "TokenMalformedError: Token payload parsing validation failed (corrupt or modified parameters)."
            ),
            "content": error_example(TokenMalformedError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "TokenExpiredError: The validation timeframe window for the provided token signature has lapsed. "
                "InvalidCredentialsError: The refresh payload is missing its subject, or the token has already "
                "been revoked or invalidated."
            ),
            "content": error_example(TokenExpiredError, InvalidCredentialsError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database context mutation exception during token lifecycle rotation.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def refresh_token_rotation(
    token_data: Annotated[RefreshTokenContext, Depends(get_user_id_from_valid_refresh_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.rotate_refresh_token(token_data.user_id, token_data.token)


@router.post(
    "/{provider}",
    response_model=OAuthSignInResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Provider credential verified. `outcome` discriminates the result: LOGGED_IN or CREATED carry a "
                "token pair; LINK_REQUIRED carries none and means an account with this email already exists "
                "under a different authentication method -- the frontend should prompt the user to log in with "
                "that method and link this provider from there (see POST /users/me/auth-providers/{provider})."
            )
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": "InvalidOAuthCredentialError: The provided credential failed cryptographic verification.",
            "content": error_example(InvalidOAuthCredentialError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "OAuthAccountCreationConflictError: A concurrent sign-in for this same identity left this "
                "request unable to resolve to an account. Extremely rare; retrying the request resolves it."
            ),
            "content": error_example(OAuthAccountCreationConflictError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. `provider` is not a recognized authentication provider."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected global backend execution failure or persistence error.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponseModel,
            "description": "GatewayConfigurationError: This authentication provider is not currently configured.",
            "content": error_example(GatewayConfigurationError),
        },
    },
)
async def sign_in_with_provider(
    provider: AuthProviderName,
    payload: OAuthSignInRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> OAuthSignInResponse:
    return await auth_service.sign_in_with_provider(provider, payload.credential)
