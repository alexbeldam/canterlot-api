from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.club import ClubOnboarding
from canterlot.dto.invite import InvitePreviewResponse
from canterlot.models import UserModel
from canterlot.routers.responses import (
    ACCEPT_INVITATION_RESPONSES,
    PREVIEW_INVITATION_RESPONSES,
)
from canterlot.services import InviteService
from canterlot.types import ClubOnboardingStatus, UsernameStr
from canterlot.use_cases import AcceptInviteUseCase

from .dependencies.providers import get_accept_invite_use_case, get_current_user, get_invite_service

router = APIRouter(prefix="/invites", tags=["Invitations"])


@router.get(
    "/{invite_id}/preview",
    operation_id="previewInvitation",
    response_model=InvitePreviewResponse,
    status_code=status.HTTP_200_OK,
    responses=PREVIEW_INVITATION_RESPONSES,
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
    responses=ACCEPT_INVITATION_RESPONSES,
)
async def accept_invitation(
    invite_id: str,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[AcceptInviteUseCase, Depends(get_accept_invite_use_case)],
    response: Response,
) -> ClubOnboarding:
    onboarding = await use_case.execute(
        invite_id=invite_id,
        current_user=current_user,
    )

    if onboarding.status == ClubOnboardingStatus.PENDING_APPROVAL:
        response.status_code = status.HTTP_202_ACCEPTED

    return onboarding
