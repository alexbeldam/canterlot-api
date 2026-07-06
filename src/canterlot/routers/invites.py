from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.dto.club import ClubOnboarding
from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.enums import ClubOnboardingStatus
from canterlot.models.user import UserModel
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import ClubService, InviteService

from .dependencies import get_club_service, get_current_user, get_invite_service

router = APIRouter(prefix="/invites", tags=["Invitations"])


@router.post(
    "/{invite_id}/accept",
    response_model=ClubOnboarding,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: {"description": "Invitation accepted; club onboarding outcome returned."},
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "TokenMalformedError or InvalidInviteTokenError: The bearer token is malformed, or the invite_id "
                "does not correspond to an existing invitation."
            ),
            "content": error_example(TokenMalformedError, InvalidInviteTokenError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired."
            ),
            "content": error_example(InvalidCredentialsError, TokenExpiredError),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": (
                "DirectInviteIdentityMismatchError: This direct invitation is bound to a different user's email."
            ),
            "content": error_example(DirectInviteIdentityMismatchError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: The club associated with this invitation no longer exists.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_410_GONE: {
            "model": ErrorResponseModel,
            "description": "InviteLinkDeactivatedError: This invitation has been deactivated or has expired.",
            "content": error_example(InviteLinkDeactivatedError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def accept_invitation(
    invite_id: str,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
):
    validated_invite = await invite_service.validate_incoming_invite(
        invite_id=invite_id,
        user_email=current_user.email,
    )

    onboarding = await club_service.admit_user(
        club_id=validated_invite.club_id,
        user_id=PydanticObjectId(current_user.id),
        is_direct=validated_invite.is_direct,
    )

    if onboarding and onboarding.status in [ClubOnboardingStatus.JOINED, ClubOnboardingStatus.PENDING_APPROVAL]:
        await invite_service.register_invite_usage(invite_id)

    return onboarding
