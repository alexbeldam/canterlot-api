from typing import Annotated, cast

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from canterlot.dto.auth import AccessTokenResponse, CreateSessionRequest
from canterlot.exceptions import (
    GatewayConfigurationError,
    InvalidCredentialsError,
    InvalidOAuthCredentialError,
    OAuthAccountCreationConflictError,
    OAuthLinkRequiredError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.enums import AuthOutcome, AuthProviderName, SessionType
from canterlot.models.user import UsernameStr
from canterlot.routers.cookies import clear_refresh_token_cookie, set_refresh_token_cookie
from canterlot.routers.dependencies import (
    RefreshTokenContext,
    get_auth_service,
    get_optional_refresh_token_context,
    get_user_id_from_valid_refresh_token,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/sessions",
    operation_id="createSession",
    response_model=AccessTokenResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Session created (password login, or an OAuth credential matched an existing linked account). "
                "Access token returned in the body; the refresh token is set as an httpOnly session cookie."
            )
        },
        status.HTTP_201_CREATED: {
            "description": (
                "OAuth credential verified and a new user account was created from this identity. Access token "
                "returned in the body; the refresh token is set as an httpOnly session cookie."
            )
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError: Incorrect username/password combination. "
                "InvalidOAuthCredentialError: The provided OAuth credential failed cryptographic verification."
            ),
            "content": error_example(InvalidCredentialsError, InvalidOAuthCredentialError),
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponseModel,
            "description": (
                "OAuthAccountCreationConflictError: A concurrent sign-in for this same identity left this "
                "request unable to resolve to an account. Extremely rare; retrying the request resolves it. "
                "OAuthLinkRequiredError: The OAuth credential's identity resolves to an account that already "
                "exists under a different authentication method -- the frontend should prompt the user to log "
                "in with that method and link this provider from there (see "
                "POST /users/me/auth-providers/{provider})."
            ),
            "content": error_example(OAuthAccountCreationConflictError, OAuthLinkRequiredError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Validation error. Fields don't match `type` (PASSWORD requires username+password, OAUTH "
                "requires provider+credential), or `provider` is not a recognized authentication provider."
            )
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
async def create_session(
    payload: CreateSessionRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    if payload.type is SessionType.PASSWORD:
        login_result = await auth_service.login_user(
            username=cast(UsernameStr, payload.username),
            plain_password=cast(str, payload.password),
        )
        set_refresh_token_cookie(response, login_result.refresh_token)
        return AccessTokenResponse(access_token=login_result.access_token)

    oauth_result = await auth_service.sign_in_with_provider(
        cast(AuthProviderName, payload.provider),
        cast(str, payload.credential),
    )

    if oauth_result.outcome == AuthOutcome.CREATED:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = "/v1/users/me"

    set_refresh_token_cookie(response, oauth_result.refresh_token)

    return AccessTokenResponse(access_token=oauth_result.access_token)


@router.post(
    "/login",
    include_in_schema=False,
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    # Hidden from the OpenAPI schema -- this exists only so Swagger's built-in OAuth2-password
    # "Authorize" popup has a real, form-encoded token endpoint to POST to. Real clients use
    # POST /auth/sessions; this is never meant to be a second public way to log in.
    result = await auth_service.login_user(
        username=form_data.username,
        plain_password=form_data.password,
    )
    set_refresh_token_cookie(response, result.refresh_token)
    return AccessTokenResponse(access_token=result.access_token)


@router.put(
    "/sessions/current",
    operation_id="rotateSession",
    response_model=AccessTokenResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Session rotated successfully. Old session invalidated; a new access token is returned in the "
                "body and a new refresh cookie is set."
            )
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": (
                "TokenMalformedError: Token payload parsing validation failed (corrupt or modified parameters)."
            ),
            "content": error_example(TokenMalformedError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "TokenExpiredError: The validation timeframe window for the provided token signature has lapsed. "
                "InvalidCredentialsError: The refresh cookie is missing, its payload is missing a subject, or "
                "the token has already been revoked or invalidated."
            ),
            "content": error_example(TokenExpiredError, InvalidCredentialsError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database context mutation exception during token lifecycle rotation.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def rotate_session(
    token_data: Annotated[RefreshTokenContext, Depends(get_user_id_from_valid_refresh_token)],
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    result = await auth_service.rotate_refresh_token(token_data.user_id, token_data.token)
    set_refresh_token_cookie(response, result.refresh_token)
    return AccessTokenResponse(access_token=result.access_token)


@router.delete(
    "/sessions/current",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Current session logged out and its refresh cookie cleared. Also returned, as a no-op, when "
                "there was no active session to end."
            )
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def logout(
    token_data: Annotated[RefreshTokenContext | None, Depends(get_optional_refresh_token_context)],
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    clear_refresh_token_cookie(response)

    if token_data is None:
        return

    await auth_service.logout(token_data.user_id, token_data.token)
