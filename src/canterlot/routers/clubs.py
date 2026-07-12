from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.dto.club import ClubCreateRequest, ClubDetailResponse, ClubResponse
from canterlot.dto.invite import DirectInvitePayload, InviteTokenResponse
from canterlot.exceptions import (
    CannotTransferOwnershipToSelfError,
    FormerOwnerProtectedError,
    InvalidCredentialsError,
    InviteLinkDeactivatedError,
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

router = APIRouter(prefix="/clubs", tags=["Clubs"])

_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY = Depends(rate_limit_club_owner_action("club-ownership-action"))


@router.post(
    "",
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
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    res = await club_service.create_new_club(creator_id=current_user_id, data=payload)

    await invite_service.rotate_public_link(club_id=PydanticObjectId(res.id), user_id=current_user_id)

    member_usernames = await club_service.resolve_member_usernames(res.members)

    return ClubResponse.from_model(res, user_usernames=member_usernames)


@router.get(
    "/{club_slug}",
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


@router.post(
    "/{club_slug}/pending-approvals/{username}/approve",
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


@router.post(
    "/{club_slug}/pending-approvals/{username}/reject",
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
    "/{club_slug}/invites/rotate",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteTokenResponse,
    responses={
        status.HTTP_201_CREATED: {
            "description": "Public invite link successfully rotated. Returns the new cryptographic token."
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
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Internal database write error while saving the mutated invite token slot.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def rotate_public_admission_link(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    new_token = await invite_service.rotate_public_link(club_id, current_user_id)

    return InviteTokenResponse(invite_token=new_token)


@router.post(
    "/{club_slug}/invites/direct",
    response_model=InviteTokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "Cryptographically secure direct identity invitation token generated successfully."
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
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. Target payload does not conform to a valid email address requirement.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected engine error encountered during token serialization signature routines.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def create_direct_invite(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    payload: DirectInvitePayload,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    token = await invite_service.create_direct_invite(
        club_id=club_id,
        issuer_id=current_user_id,
        target_email=payload.email,
    )

    return InviteTokenResponse(invite_token=token)


@router.delete(
    "/{club_slug}/members/{username}",
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


@router.post(
    "/{club_slug}/members/{username}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_CLUB_OWNERSHIP_ACTION_RATE_LIMIT_DEPENDENCY],
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Ownership transferred. The caller is now ADMIN and protected from removal for 30 days; "
                "the target is now OWNER and cannot initiate another transfer for 30 days."
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
async def transfer_club_ownership(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    target_user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_username)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> None:
    await club_service.transfer_ownership(club_id, current_user_id, target_user_id)


@router.post(
    "/{club_slug}/transfer-ownership/reclaim",
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
    response_model=str,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: {"description": "Currently active public invite token for the club returned."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given slug.",
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
):
    return await invite_service.get_public_link(club_id)
