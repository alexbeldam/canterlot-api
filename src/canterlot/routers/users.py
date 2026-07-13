from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.dto.auth import ConnectedProvidersResponse, LinkProviderRequest, TokenResponse
from canterlot.dto.user import ChangePasswordRequest, UpdateProfileRequest, UserProfileResponse
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    BookNotFoundError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    InvalidOAuthCredentialError,
    LastAuthenticationMethodError,
    TokenExpiredError,
    TokenMalformedError,
    UsernameAlreadyExistsError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.enums import AuthProviderName
from canterlot.routers.dependencies import (
    get_auth_service,
    get_book_id_from_identifier,
    get_current_user_id,
    get_user_service,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import AuthService, UserService

profile_router = APIRouter(prefix="/users/me", tags=["Users"])
auth_providers_router = APIRouter(prefix="/users/me/auth-providers", tags=["Users"])
read_books_router = APIRouter(prefix="/users/me/read-books", tags=["Users"])


@profile_router.patch(
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


@profile_router.put(
    "/password",
    operation_id="changePassword",
    response_model=TokenResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Password changed, or set for the first time on an OAuth-only account (`current_password` is "
                "only required/verified when the account already has a password). Every other refresh token on "
                "the account is revoked and a fresh token pair is returned for the caller's own session."
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
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await auth_service.change_password(current_user_id, payload.current_password, payload.new_password)


@auth_providers_router.get(
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


@auth_providers_router.post(
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
                "InvalidOAuthCredentialError: The provided credential failed cryptographic verification."
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
    await auth_service.link_provider(current_user_id, provider, payload.credential)


@auth_providers_router.delete(
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


@read_books_router.put(
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
