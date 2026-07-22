from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.club import (
    ChangeMemberRoleRequest,
    ClubCreateRequest,
    ClubDetailResponse,
    ClubMemberProfileResponse,
    ClubResponse,
    ClubSettingsUpdateRequest,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
)
from canterlot.dto.invite import CreateInviteRequest, InviteTokenResponse
from canterlot.models import ClubModel, UserModel
from canterlot.routers.responses import (
    CHANGE_CLUB_MEMBER_ROLE_RESPONSES,
    CREATE_CLUB_RESPONSES,
    CREATE_INVITE_RESPONSES,
    CREATE_OWNERSHIP_TRANSFER_RESPONSES,
    DISSOLVE_CLUB_RESPONSES,
    GET_CLUB_MEMBER_RESPONSES,
    GET_CLUB_RESPONSES,
    GET_PUBLIC_INVITE_RESPONSES,
    LEAVE_CLUB_RESPONSES,
    RECLAIM_CLUB_OWNERSHIP_RESPONSES,
    REMOVE_CLUB_MEMBER_RESPONSES,
    REVIEW_PENDING_REQUEST_RESPONSES,
    UPDATE_CLUB_SETTINGS_RESPONSES,
)
from canterlot.services import ClubService, InviteService
from canterlot.use_cases import (
    ApprovePendingMemberUseCase,
    ChangeMemberRoleUseCase,
    CreateClubUseCase,
    CreateInviteUseCase,
    DissolveClubUseCase,
    ReclaimClubOwnershipUseCase,
    RemoveClubMemberUseCase,
    TransferClubOwnershipUseCase,
)

from .dependencies.providers import (
    get_approve_pending_member_use_case,
    get_change_member_role_use_case,
    get_club_from_slug,
    get_club_id_from_slug,
    get_club_service,
    get_create_club_use_case,
    get_create_invite_use_case,
    get_current_user,
    get_current_user_id,
    get_dissolve_club_use_case,
    get_invite_service,
    get_reclaim_club_ownership_use_case,
    get_remove_club_member_use_case,
    get_transfer_club_ownership_use_case,
    get_user_from_username,
    get_user_id_from_username,
)
from .dependencies.rate_limiter import (
    rate_limit_club_moderation,
    rate_limit_club_owner_action,
    rate_limit_create_invite_attempt,
)

router = APIRouter(prefix="/clubs", tags=["Clubs"])

_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY = Depends(rate_limit_club_owner_action("club-ownership-action"))
_APPROVE_PENDING_RATE_LIMIT = Depends(rate_limit_club_moderation("approve_pending"))
_REMOVE_MEMBER_RATE_LIMIT = Depends(rate_limit_club_moderation("remove_member"))
_CHANGE_ROLE_RATE_LIMIT = Depends(rate_limit_club_moderation("change_role"))


@router.post(
    "",
    operation_id="createClub",
    response_model=ClubResponse,
    status_code=status.HTTP_201_CREATED,
    responses=CREATE_CLUB_RESPONSES,
)
async def create_club(
    payload: ClubCreateRequest,
    response: Response,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    use_case: Annotated[CreateClubUseCase, Depends(get_create_club_use_case)],
) -> ClubResponse:
    club_response = await use_case.execute(
        creator_id=current_user_id,
        payload=payload,
    )

    response.headers["Location"] = f"/v1/clubs/{club_response.slug}"

    return club_response


@router.patch(
    "/{club_slug}/settings",
    operation_id="updateClubSettings",
    response_model=ClubResponse,
    responses=UPDATE_CLUB_SETTINGS_RESPONSES,
)
async def update_club_settings(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    payload: ClubSettingsUpdateRequest,
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubResponse:
    updated = await club_service.update_settings(club, current_user_id, payload)
    member_usernames = await club_service.resolve_member_usernames(updated.members)

    return ClubResponse.from_model(updated, user_usernames=member_usernames)


@router.get(
    "/{club_slug}",
    operation_id="getClub",
    response_model=ClubDetailResponse | ClubResponse,
    responses=GET_CLUB_RESPONSES,
)
async def get_club(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubDetailResponse | ClubResponse:
    view = await club_service.get_club_view(club, current_user_id)

    if view.pending_usernames is not None:
        return ClubDetailResponse.from_model_with_pending(
            view.club,
            view.member_usernames,
            view.pending_usernames,
            current_user_id,
        )

    return ClubResponse.from_model(view.club, view.member_usernames)


@router.delete(
    "/{club_slug}",
    operation_id="dissolveClub",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses=DISSOLVE_CLUB_RESPONSES,
)
async def dissolve_club(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[DissolveClubUseCase, Depends(get_dissolve_club_use_case)],
) -> None:
    await use_case.execute(
        club=club,
        owner=current_user,
    )


@router.patch(
    "/{club_slug}/pending-approvals/{username}",
    operation_id="approvePendingRequest",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_APPROVE_PENDING_RATE_LIMIT],
    responses=REVIEW_PENDING_REQUEST_RESPONSES,
)
async def approve_pending_request(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    target_user: Annotated[UserModel, Depends(get_user_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    use_case: Annotated[ApprovePendingMemberUseCase, Depends(get_approve_pending_member_use_case)],
) -> None:
    await use_case.execute(
        club=club,
        reviewer_id=current_user_id,
        target_user=target_user,
    )


@router.delete(
    "/{club_slug}/pending-approvals/{username}",
    operation_id="rejectPendingRequest",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=REVIEW_PENDING_REQUEST_RESPONSES,
)
async def reject_pending_request(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    target_user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.review_pending_request(club_id, current_user_id, target_user_id, approve=False)


@router.post(
    "/{club_slug}/invites",
    operation_id="createInvite",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteTokenResponse,
    responses=CREATE_INVITE_RESPONSES,
    dependencies=[Depends(rate_limit_create_invite_attempt)],
)
async def create_invite(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    payload: CreateInviteRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[CreateInviteUseCase, Depends(get_create_invite_use_case)],
    response: Response,
) -> InviteTokenResponse:
    res = await use_case.execute(club, current_user, payload)

    response.headers["Location"] = f"/v1/invites/{res.invite_token}/preview"

    return res


@router.delete(
    "/{club_slug}/members/me",
    operation_id="leaveClub",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=LEAVE_CLUB_RESPONSES,
)
async def leave_club(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.leave_club(club, current_user_id)


@router.get(
    "/{club_slug}/members/{username}",
    operation_id="getClubMember",
    response_model=ClubMemberProfileResponse,
    responses=GET_CLUB_MEMBER_RESPONSES,
)
async def get_club_member(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    target_user: Annotated[UserModel, Depends(get_user_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubMemberProfileResponse:
    member = await club_service.get_member_profile(club, current_user_id, PydanticObjectId(target_user.id))

    return ClubMemberProfileResponse.from_models(target_user, member)


@router.delete(
    "/{club_slug}/members/{username}",
    operation_id="removeClubMember",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_REMOVE_MEMBER_RATE_LIMIT],
    responses=REMOVE_CLUB_MEMBER_RESPONSES,
)
async def remove_club_member(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    target_user: Annotated[UserModel, Depends(get_user_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    use_case: Annotated[RemoveClubMemberUseCase, Depends(get_remove_club_member_use_case)],
) -> None:
    await use_case.execute(
        club=club,
        remover_id=current_user_id,
        target_user=target_user,
    )


@router.put(
    "/{club_slug}/members/{username}/role",
    operation_id="changeClubMemberRole",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_CHANGE_ROLE_RATE_LIMIT],
    responses=CHANGE_CLUB_MEMBER_ROLE_RESPONSES,
)
async def change_club_member_role(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    target_user: Annotated[UserModel, Depends(get_user_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    payload: ChangeMemberRoleRequest,
    use_case: Annotated[ChangeMemberRoleUseCase, Depends(get_change_member_role_use_case)],
) -> None:
    await use_case.execute(
        club=club,
        caller_id=current_user_id,
        target_user=target_user,
        new_role=payload.role,
    )


@router.post(
    "/{club_slug}/ownership-transfers",
    operation_id="createOwnershipTransfer",
    status_code=status.HTTP_201_CREATED,
    response_model=OwnershipTransferResponse,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses=CREATE_OWNERSHIP_TRANSFER_RESPONSES,
)
async def create_ownership_transfer(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    payload: OwnershipTransferRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[TransferClubOwnershipUseCase, Depends(get_transfer_club_ownership_use_case)],
) -> OwnershipTransferResponse:
    return await use_case.execute(
        club=club,
        current_owner=current_user,
        payload=payload,
    )


@router.delete(
    "/{club_slug}/ownership-transfers/current",
    operation_id="reclaimClubOwnership",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses=RECLAIM_CLUB_OWNERSHIP_RESPONSES,
)
async def reclaim_club_ownership(
    club: Annotated[ClubModel, Depends(get_club_from_slug)],
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[ReclaimClubOwnershipUseCase, Depends(get_reclaim_club_ownership_use_case)],
) -> None:
    await use_case.execute(
        club=club,
        reclaiming_owner=current_user,
    )


@router.get(
    "/{club_slug}/invites/public",
    operation_id="getPublicInvite",
    response_model=InviteTokenResponse,
    status_code=status.HTTP_200_OK,
    responses=GET_PUBLIC_INVITE_RESPONSES,
)
async def get_public_invite(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
) -> InviteTokenResponse:
    return InviteTokenResponse(invite_token=await invite_service.get_public_link(club_id))
