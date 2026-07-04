from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from canterlot.models import ErrorResponseModel, RegisterResponse, TokenResponse, UserRegisterRequest
from canterlot.models.enums import ClubOnboardingStatus
from canterlot.models.user import UsernameStr
from canterlot.routers.dependencies import (
    get_auth_service,
    get_club_service,
    get_invite_service,
    get_user_id_from_valid_refresh_token,
)
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
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": (
                "DirectInviteIdentityMismatchError: The provided invite_id is a direct invitation bound to a "
                "different email address than the one being registered."
            ),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: The club associated with the provided invite_id no longer exists.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "UsernameAlreadyExistsError or EmailAlreadyExistsError: The username or email string "
                "is already bound to a different profile."
            ),
        },
        status.HTTP_410_GONE: {
            "model": ErrorResponseModel,
            "description": (
                "InviteLinkDeactivatedError: The provided invite_id has been deactivated, rotated, or has expired."
            ),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Validation error. Request body values violate type constraints or payload formatting requirements."
            )
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected global backend execution failure or persistence error.",
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
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. Form values missing or incorrectly structured during transmission."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected runtime engine error during validation processing.",
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
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "TokenExpiredError: The validation timeframe window for the provided token signature has lapsed. "
                "InvalidCredentialsError: The refresh payload is missing its subject, or the token has already "
                "been revoked or invalidated."
            ),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database context mutation exception during token lifecycle rotation.",
        },
    },
)
async def refresh_token_rotation(
    token_data: Annotated[tuple[PydanticObjectId, str], Depends(get_user_id_from_valid_refresh_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    user_id, old_refresh_token = token_data

    return await auth_service.rotate_refresh_token(user_id, old_refresh_token)
