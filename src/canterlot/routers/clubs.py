from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from canterlot.exceptions import (
    InvalidCredentialsError,
    InviteLinkDeactivatedError,
    TokenExpiredError,
    TokenMalformedError,
    UnauthorizedClubMemberError,
)
from canterlot.models import (
    ClubCreateRequest,
    ClubModel,
    ErrorResponseModel,
)
from canterlot.routers.dependencies import get_club_service, get_current_user_id, get_invite_service
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import ClubService, InviteService
from canterlot.utils.format import NormalizedEmailStr

router = APIRouter(prefix="/clubs", tags=["Clubs"])


class DirectInvitePayload(BaseModel):
    email: NormalizedEmailStr


class JoinClubPayload(BaseModel):
    invite_token: str


class InviteTokenResponse(BaseModel):
    invite_token: str


@router.post(
    "",
    response_model=ClubModel,
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

    return res


@router.post(
    "/{club_id}/invites/rotate",
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
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_id path parameter is not a valid object identifier.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Internal database write error while saving the mutated invite token slot.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def rotate_public_admission_link(
    club_id: PydanticObjectId,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    new_token = await invite_service.rotate_public_link(club_id, current_user_id)

    return InviteTokenResponse(invite_token=new_token)


@router.post(
    "/{club_id}/invites/direct",
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
    club_id: PydanticObjectId,
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


@router.get(
    "/{club_id}/invites/public",
    response_model=str,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_200_OK: {"description": "Currently active public invite token for the club returned."},
        status.HTTP_410_GONE: {
            "model": ErrorResponseModel,
            "description": "InviteLinkDeactivatedError: This club has no active public invite link.",
            "content": error_example(InviteLinkDeactivatedError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_id path parameter is not a valid object identifier."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_public_invite(
    club_id: PydanticObjectId,
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
):
    return await invite_service.get_public_link(club_id)
