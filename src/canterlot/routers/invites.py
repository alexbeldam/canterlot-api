from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.club import ClubOnboarding
from canterlot.dto.invite import InvitePreviewResponse
from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
    MemberBannedError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.enums import ClubOnboardingStatus
from canterlot.models.user import UserModel, UsernameStr
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import ClubService, InviteService

from .dependencies import get_club_service, get_current_user, get_invite_service

router = APIRouter(prefix="/invites", tags=["Invitations"])


@router.get(
    "/{invite_id}/preview",
    operation_id="previewInvitation",
    response_model=InvitePreviewResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: {"description": "Invite metadata returned for a not-yet-authenticated viewer."},
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "InvalidInviteTokenError: The invite_id does not correspond to an existing invitation.",
            "content": error_example(InvalidInviteTokenError),
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
async def preview_invitation(
    invite_id: str,
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    invited_by: UsernameStr | None = None,
):
    return await invite_service.get_preview_metadata(invite_id, invited_by=invited_by)


@router.patch(
    "/{invite_id}",
    operation_id="acceptInvitation",
    response_model=ClubOnboarding,
    responses={
        status.HTTP_200_OK: {
            "description": "Invitation accepted; the caller either joined outright or was already a member."
        },
        status.HTTP_202_ACCEPTED: {
            "description": "Invitation accepted; the caller was queued in the club's pending-approval list."
        },
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
                "DirectInviteIdentityMismatchError: This direct invitation is bound to a different user's email. "
                "MemberBannedError: The caller is banned from this club; only a new direct invite lifts a ban."
            ),
            "content": error_example(DirectInviteIdentityMismatchError, MemberBannedError),
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
    response: Response,
) -> ClubOnboarding:
    validated_invite = await invite_service.validate_incoming_invite(
        invite_id=invite_id,
        user_email=current_user.email,
    )

    onboarding = await club_service.admit_user(
        club_id=validated_invite.club_id,
        user_id=PydanticObjectId(current_user.id),
        is_direct=validated_invite.is_direct,
    )

    if onboarding.status == ClubOnboardingStatus.BANNED:
        raise MemberBannedError("This user is banned from this club.")

    if onboarding.status in [ClubOnboardingStatus.JOINED, ClubOnboardingStatus.PENDING_APPROVAL]:
        await invite_service.register_invite_usage(invite_id)

    if onboarding.status == ClubOnboardingStatus.PENDING_APPROVAL:
        response.status_code = status.HTTP_202_ACCEPTED

    return onboarding
