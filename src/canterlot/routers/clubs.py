from typing import Annotated, cast

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.club import (
    ChangeMemberRoleRequest,
    ClubCreateRequest,
    ClubDetailResponse,
    ClubResponse,
    ClubSettingsUpdateRequest,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
)
from canterlot.dto.invite import CreateInviteRequest, InviteTokenResponse
from canterlot.exceptions import (
    CannotChangeOwnerRoleError,
    CannotTransferOwnershipToSelfError,
    ClubOwnerCannotLeaveError,
    FormerOwnerProtectedError,
    InvalidCredentialsError,
    InviteLinkDeactivatedError,
    MemberRoleChangeConflictError,
    OwnershipReclaimWindowExpiredError,
    OwnershipTransferConflictError,
    OwnershipTransferCooldownError,
    PendingRequestNotFoundError,
    RateLimitExceededError,
    TokenExpiredError,
    TokenMalformedError,
    UnauthorizedClubMemberError,
    UserNotFoundError,
)
from canterlot.exceptions.club import ClubMemberNotFoundError, ClubNotFoundError
from canterlot.models import ErrorResponseModel
from canterlot.models.club import ClubSlugStr
from canterlot.models.enums import InviteType
from canterlot.routers.dependencies import (
    get_club_id_from_slug,
    get_club_service,
    get_current_user_id,
    get_invite_service,
    get_user_id_from_username,
    rate_limit_club_owner_action,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import ClubService, InviteService
from canterlot.utils.format import NormalizedEmailStr

router = APIRouter(prefix="/clubs", tags=["Clubs"])

_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY = Depends(rate_limit_club_owner_action("club-ownership-action"))


@router.post(
    "",
    operation_id="createClub",
    response_model=ClubResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "Club workspace initialized successfully, with the creator saved as the OWNER tier root."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
                "UnauthorizedClubMemberError: The newly created club's initial public invite link could not be "
                "rotated because the creator's ownership role could not be verified."
            ),
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. Request payload violates payload field lengths or type constraints.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected engine error encountered during database collection writing routines.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def create_club(
    payload: ClubCreateRequest,
    response: Response,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    res = await club_service.create_new_club(creator_id=current_user_id, data=payload)

    await invite_service.rotate_public_link(club_id=PydanticObjectId(res.id), user_id=current_user_id)

    member_usernames = await club_service.resolve_member_usernames(res.members)

    response.headers["Location"] = f"/api/v1/clubs/{res.slug}"

    return ClubResponse.from_model(res, user_usernames=member_usernames)


@router.patch(
    "/{club_slug}/settings",
    operation_id="updateClubSettings",
    response_model=ClubResponse,
    responses={
        status.HTTP_200_OK: {"description": "The club's settings were updated successfully."},
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER/ADMIN standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. No fields provided, or a field violates its constraints.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def update_club_settings(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    payload: ClubSettingsUpdateRequest,
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubResponse:
    updated = await club_service.update_settings(club_id, current_user_id, payload)
    member_usernames = await club_service.resolve_member_usernames(updated.members)

    return ClubResponse.from_model(updated, user_usernames=member_usernames)


@router.get(
    "/{club_slug}",
    operation_id="getClub",
    response_model=ClubDetailResponse | ClubResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Club metadata retrieved. Callers with OWNER or ADMIN standing additionally receive the "
                "pending-approval queue (ClubDetailResponse); other members receive the same public shape as "
                "club creation (ClubResponse). banned_users is never returned to anyone."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The requesting user is not a member of this club.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_club(
    club_slug: ClubSlugStr,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubDetailResponse | ClubResponse:
    view = await club_service.get_club_view(club_slug, current_user_id)

    if view.pending_usernames is not None:
        return ClubDetailResponse.from_model_with_pending(view.club, view.member_usernames, view.pending_usernames)

    return ClubResponse.from_model(view.club, view.member_usernames)


@router.delete(
    "/{club_slug}",
    operation_id="dissolveClub",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Club dissolved. Every member is removed (not banned) and the club document itself no longer "
                "exists; its slug becomes available for reuse and all outstanding invite links are permanently dead."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "FormerOwnerProtectedError: This club has a former owner still protected from removal (transferred "
                "ownership away less than 30 days ago); dissolution is blocked until that window elapses."
            ),
            "content": error_example(FormerOwnerProtectedError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def dissolve_club(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.dissolve_club(club_id, current_user_id)


@router.patch(
    "/{club_slug}/pending-approvals/{username}",
    operation_id="approvePendingRequest",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": "Join request approved; the user is now a MEMBER and no longer appears in the queue."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER or ADMIN standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError: No club exists with the given slug. "
                "UserNotFoundError: No user exists with the given username. "
                "PendingRequestNotFoundError: This user has no pending join request for this club."
            ),
            "content": error_example(ClubNotFoundError, UserNotFoundError, PendingRequestNotFoundError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def approve_pending_request(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    target_user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.review_pending_request(club_id, current_user_id, target_user_id, approve=True)


@router.delete(
    "/{club_slug}/pending-approvals/{username}",
    operation_id="rejectPendingRequest",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Join request rejected — a plain decline, not a ban. The user may request to join again later."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER or ADMIN standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError: No club exists with the given slug. "
                "UserNotFoundError: No user exists with the given username. "
                "PendingRequestNotFoundError: This user has no pending join request for this club."
            ),
            "content": error_example(ClubNotFoundError, UserNotFoundError, PendingRequestNotFoundError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
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
    responses={
        status.HTTP_201_CREATED: {
            "description": (
                "Invite created. A `public`-type request rotates (replaces) the club's active public link; a "
                "`direct`-type request generates a single-use, email-bound invitation."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
                "UnauthorizedClubMemberError: Requesting user lacks Administrative or Owner permissions for this club."
            ),
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Validation error. `email` is required for a `direct` invite and forbidden for a `public` one, "
                "or `email` does not conform to a valid email address requirement."
            ),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected engine error encountered during token serialization or persistence.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def create_invite(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    payload: CreateInviteRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    response: Response,
) -> InviteTokenResponse:
    if payload.type is InviteType.PUBLIC:
        token = await invite_service.rotate_public_link(club_id, current_user_id)
    else:
        token = await invite_service.create_direct_invite(
            club_id=club_id,
            issuer_id=current_user_id,
            target_email=cast(NormalizedEmailStr, payload.email),
        )

    response.headers["Location"] = f"/api/v1/invites/{token}/preview"

    return InviteTokenResponse(invite_token=token)


@router.delete(
    "/{club_slug}/members/me",
    operation_id="leaveClub",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Caller left the club voluntarily. This is never a ban — the caller can rejoin later via any "
                "public link or invite."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller is not a member of this club.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "ClubOwnerCannotLeaveError: The caller is this club's OWNER, who can never leave directly. "
                "FormerOwnerProtectedError: The caller transferred ownership away less than 30 days ago and is "
                "still protected from leaving."
            ),
            "content": error_example(ClubOwnerCannotLeaveError, FormerOwnerProtectedError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def leave_club(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.leave_club(club_id, current_user_id)


@router.delete(
    "/{club_slug}/members/{username}",
    operation_id="removeClubMember",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Member removed and banned from the club in the same operation — an admin-initiated removal is "
                "always a ban. The user can only rejoin via a direct invite; public links won't admit them."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
                "UnauthorizedClubMemberError: The caller does not hold OWNER/ADMIN standing, or does not strictly "
                "outrank the target (an ADMIN can never remove another ADMIN or the OWNER)."
            ),
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError: No club exists with the given slug. "
                "UserNotFoundError: No user exists with the given username. "
                "ClubMemberNotFoundError: The target user is not a member of this club."
            ),
            "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "FormerOwnerProtectedError: The target transferred ownership away less than 30 days ago and is "
                "still protected from removal by the current OWNER."
            ),
            "content": error_example(FormerOwnerProtectedError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def remove_club_member(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    target_user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.remove_member(club_id, current_user_id, target_user_id)


@router.put(
    "/{club_slug}/members/{username}/role",
    operation_id="changeClubMemberRole",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "The member's role was changed successfully."},
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "TokenMalformedError: The bearer token is corrupt, malformed, or altered. "
                "CannotChangeOwnerRoleError: The target is this club's OWNER; ownership can only be changed "
                "via the transfer-ownership action."
            ),
            "content": error_example(TokenMalformedError, CannotChangeOwnerRoleError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError: No club exists with the given slug. "
                "UserNotFoundError: No user exists with the given username. "
                "ClubMemberNotFoundError: The target user is not a member of this club."
            ),
            "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "FormerOwnerProtectedError: The target transferred ownership away less than 30 days ago and is "
                "still protected from further demotion. "
                "MemberRoleChangeConflictError: This club's membership changed before the role update could "
                "complete."
            ),
            "content": error_example(FormerOwnerProtectedError, MemberRoleChangeConflictError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def change_club_member_role(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    target_user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    payload: ChangeMemberRoleRequest,
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.change_member_role(club_id, current_user_id, target_user_id, payload.role)


@router.post(
    "/{club_slug}/ownership-transfers",
    operation_id="createOwnershipTransfer",
    status_code=status.HTTP_201_CREATED,
    response_model=OwnershipTransferResponse,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses={
        status.HTTP_201_CREATED: {
            "description": (
                "Ownership transferred. The caller is now ADMIN and protected from removal for 30 days; "
                "the target is now OWNER and cannot initiate another transfer for 30 days. Returns the "
                "deadline by which the caller can still reclaim ownership."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "TokenMalformedError: The bearer token is corrupt, malformed, or altered. "
                "CannotTransferOwnershipToSelfError: The target username is the caller's own account."
            ),
            "content": error_example(TokenMalformedError, CannotTransferOwnershipToSelfError),
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
            "description": "UnauthorizedClubMemberError: The caller does not hold OWNER standing.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError: No club exists with the given slug. "
                "UserNotFoundError: No user exists with the given username. "
                "ClubMemberNotFoundError: The target user is not a member of this club."
            ),
            "content": error_example(ClubNotFoundError, UserNotFoundError, ClubMemberNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "OwnershipTransferCooldownError: The caller received ownership less than 30 days ago "
                "and the target is not this club's recorded former owner. "
                "OwnershipTransferConflictError: This club's membership changed before the transfer could complete."
            ),
            "content": error_example(OwnershipTransferCooldownError, OwnershipTransferConflictError),
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponseModel,
            "description": "RateLimitExceededError: Too many ownership actions on this club by this caller.",
            "content": error_example(RateLimitExceededError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def create_ownership_transfer(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    payload: OwnershipTransferRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> OwnershipTransferResponse:
    reclaim_deadline = await club_service.transfer_ownership(club_id, current_user_id, payload.new_owner_username)

    return OwnershipTransferResponse(reclaim_deadline=reclaim_deadline)


@router.delete(
    "/{club_slug}/ownership-transfers/current",
    operation_id="reclaimClubOwnership",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Transfer reversed. The caller is OWNER again; the reverted new-Owner is back to ADMIN. "
                "No cooldowns or protections carry over from the reversed transfer."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
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
            "description": "UnauthorizedClubMemberError: The caller is not this club's recorded former owner.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "OwnershipReclaimWindowExpiredError: More than 24 hours have passed since the transfer. "
                "OwnershipTransferConflictError: This club's membership changed before the reclaim could complete."
            ),
            "content": error_example(OwnershipReclaimWindowExpiredError, OwnershipTransferConflictError),
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponseModel,
            "description": "RateLimitExceededError: Too many ownership actions on this club by this caller.",
            "content": error_example(RateLimitExceededError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def reclaim_club_ownership(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.reclaim_ownership(club_id, current_user_id)


@router.get(
    "/{club_slug}/invites/public",
    operation_id="getPublicInvite",
    response_model=InviteTokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: {"description": "Currently active public invite token for the club returned."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_410_GONE: {
            "model": ErrorResponseModel,
            "description": "InviteLinkDeactivatedError: This club has no active public invite link.",
            "content": error_example(InviteLinkDeactivatedError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_public_invite(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
) -> InviteTokenResponse:
    return InviteTokenResponse(invite_token=await invite_service.get_public_link(club_id))
