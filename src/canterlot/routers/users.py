from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.auth import (
    AccessTokenResponse,
    ConnectedProvidersResponse,
    LinkProviderRequest,
    RegisterResponse,
    UserRegisterRequest,
)
from canterlot.dto.user import (
    ChangePasswordRequest,
    LegalAcceptanceRequest,
    SetAvatarRequest,
    UpdateProfileRequest,
    UserProfileResponse,
)
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    BookNotFoundError,
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InvalidOAuthCredentialError,
    InviteLinkDeactivatedError,
    LastAuthenticationMethodError,
    RateLimitExceededError,
    StaleLegalVersionError,
    TokenExpiredError,
    TokenMalformedError,
    UsernameAlreadyExistsError,
)
from canterlot.models import ErrorResponseModel
from canterlot.routers.cookies import set_refresh_token_cookie
from canterlot.routers.dependencies import (
    get_auth_service,
    get_book_id_from_identifier,
    get_club_service,
    get_current_user_id,
    get_invite_service,
    get_user_service,
    rate_limit_register_attempt,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import AuthService, ClubService, InviteService, UserService
from canterlot.types import AuthProviderName, ClubOnboardingStatus

router = APIRouter(prefix="/users", tags=["Users"])
_profile = APIRouter(prefix="/me", tags=["Users"])
_oauth = APIRouter(prefix="/auth-providers", tags=["Users"])
_read_books = APIRouter(prefix="/read-books", tags=["Users"])


@router.post(
    "",
    operation_id="register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_register_attempt)],
    responses={
        status.HTTP_201_CREATED: {
            "description": (
                "User account created successfully. Access token returned in the body; the refresh token is "
                "set as an httpOnly session cookie, not returned in the body."
            )
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
                "is already bound to a different profile. StaleLegalVersionError: `terms_version`/"
                "`privacy_version` don't match the currently published documents."
            ),
            "content": error_example(UsernameAlreadyExistsError, EmailAlreadyExistsError, StaleLegalVersionError),
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
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponseModel,
            "description": "RateLimitExceededError: Too many registration attempts from this IP address.",
            "content": error_example(RateLimitExceededError),
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
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
):
    validated_invite = None
    inviter_username = payload.invited_by

    if payload.invite_id:
        validated_invite = await invite_service.validate_incoming_invite(
            payload.invite_id,
            payload.email,
            payload.invited_by,
        )

        inviter_username = validated_invite.invited_by or payload.invited_by

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
            and payload.invite_id
        ):
            await invite_service.register_invite_usage(payload.invite_id)

    set_refresh_token_cookie(response, res.refresh_token)
    response.headers["Location"] = "/v1/users/me"

    return RegisterResponse(access_token=res.access_token, onboarding=onboarding)


@_profile.get(
    "",
    operation_id="getOwnProfile",
    response_model=UserProfileResponse,
    responses={
        status.HTTP_200_OK: {"description": "The caller's own profile, including email and avatar."},
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
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_own_profile(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    user = await user_service.get_profile(current_user_id)

    return UserProfileResponse.from_model(user)


@_profile.patch(
    "",
    operation_id="updateProfile",
    response_model=UserProfileResponse,
    responses={
        status.HTTP_200_OK: {"description": "The profile was updated successfully."},
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
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": "UsernameAlreadyExistsError: The requested username is already taken.",
            "content": error_example(UsernameAlreadyExistsError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. No fields provided, or a field violates its constraints."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def update_profile(
    payload: UpdateProfileRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.update_profile(current_user_id, name=payload.name, username=payload.username)
    return UserProfileResponse.from_model(updated)


@_profile.put(
    "/password",
    operation_id="changePassword",
    response_model=AccessTokenResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Password changed, or set for the first time on an OAuth-only account (`current_password` is "
                "only required/verified when the account already has a password). Every other refresh token on "
                "the account is revoked; a fresh access token is returned in the body and a new refresh cookie "
                "is set for the caller's own session."
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
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired. "
                "IncorrectPasswordError: The submitted current password does not match."
            ),
            "content": error_example(InvalidCredentialsError, TokenExpiredError, IncorrectPasswordError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. `new_password` is shorter than the minimum length."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    result = await auth_service.change_password(current_user_id, payload.current_password, payload.new_password)

    set_refresh_token_cookie(response, result.refresh_token)

    return AccessTokenResponse(access_token=result.access_token)


@_profile.put(
    "/avatar",
    operation_id="setAvatar",
    response_model=UserProfileResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Avatar set to the requested linked provider's photo; the full updated profile is returned. "
                "Calling this again with the same `source` re-resolves the value from whatever picture URL is "
                "currently stored for that provider, effectively resyncing it."
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "AuthProviderNotLinkedError: No linked account with a profile picture exists for the "
                "requested `source`."
            ),
            "content": error_example(AuthProviderNotLinkedError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. `source` is not a recognized authentication provider."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def set_avatar(
    payload: SetAvatarRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.set_avatar_source(current_user_id, payload.source)

    return UserProfileResponse.from_model(updated)


@_profile.delete(
    "/avatar",
    operation_id="clearAvatar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": ("Active provider photo cleared; the generated avatar (unchanged seed) is now showing.")
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
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def clear_avatar(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> None:
    await user_service.clear_avatar(current_user_id)


@_profile.post(
    "/avatar/seed",
    operation_id="regenerateAvatarSeed",
    response_model=UserProfileResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "The generated-avatar seed was regenerated; the full updated profile is returned. Only "
                "visible immediately if no provider photo is currently active."
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
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def regenerate_avatar_seed(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.regenerate_avatar_seed(current_user_id)

    return UserProfileResponse.from_model(updated)


@_profile.post(
    "/legal-acceptance",
    operation_id="acceptLegalDocuments",
    response_model=UserProfileResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Acceptance recorded for both documents. If the account had no `profile_completed_at` yet "
                "(a Google-created account that hasn't confirmed its profile), this call also sets it -- "
                "there is no separate 'complete onboarding' endpoint."
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
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "StaleLegalVersionError: `terms_version`/`privacy_version` don't match the currently "
                "published documents -- reload the documents and retry."
            ),
            "content": error_example(StaleLegalVersionError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. `terms_version`/`privacy_version` missing or not integers."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def accept_legal_documents(
    payload: LegalAcceptanceRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.accept_legal_documents(
        current_user_id,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
    )

    return UserProfileResponse.from_model(updated)


@_oauth.get(
    "",
    operation_id="getConnectedProviders",
    response_model=ConnectedProvidersResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Connected authentication methods returned, without exposing any internal credential."
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
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_connected_providers(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ConnectedProvidersResponse:
    return await auth_service.list_connected_providers(current_user_id)


@_oauth.post(
    "/{provider}",
    operation_id="linkProvider",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Provider linked to the authenticated account."},
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired. "
                "InvalidOAuthCredentialError: The provided credential failed verification, for a "
                "code-exchange provider (e.g. Gravatar), this also covers a missing/mismatched `redirect_uri`."
            ),
            "content": error_example(InvalidCredentialsError, TokenExpiredError, InvalidOAuthCredentialError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "AuthProviderAlreadyLinkedError: This provider credential is already linked to a different account."
            ),
            "content": error_example(AuthProviderAlreadyLinkedError),
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
async def link_provider(
    provider: AuthProviderName,
    payload: LinkProviderRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await auth_service.link_provider(current_user_id, provider, payload.credential, payload.redirect_uri)


@_oauth.delete(
    "/{provider}",
    operation_id="disconnectProvider",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Provider disconnected from the authenticated account."},
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "AuthProviderNotLinkedError: No linked account exists for this provider.",
            "content": error_example(AuthProviderNotLinkedError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "LastAuthenticationMethodError: This is the account's only remaining way to sign in; a password "
                "or another provider must be added first."
            ),
            "content": error_example(LastAuthenticationMethodError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. `provider` is not a recognized authentication provider."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def disconnect_provider(
    provider: AuthProviderName,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await auth_service.disconnect_provider(current_user_id, provider)


@_read_books.put(
    "/{identifier}",
    operation_id="markBookRead",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Book successfully recorded in the user's reading history."},
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "BookNotFoundError: No book matches the given identifier, whether it was an ISBN-10, "
                "an ISBN-13, or a provider external ID."
            ),
            "content": error_example(BookNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error. The identifier is invalid."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def mark_book_read(
    book_id: Annotated[PydanticObjectId, Depends(get_book_id_from_identifier)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> None:
    await user_service.mark_book_read(user_id=current_user_id, book_id=book_id)


_profile.include_router(_oauth)
_profile.include_router(_read_books)
router.include_router(_profile)
