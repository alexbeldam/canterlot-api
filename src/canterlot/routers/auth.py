from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import SecretStr

from canterlot.dto.auth import (
    AccessTokenResponse,
    ConfirmEmailVerificationRequest,
    CreateSessionRequest,
    RequestPasswordResetRequest,
    ResetPasswordRequest,
    ResetSessionStatusResponse,
    ValidatePasswordResetCodeRequest,
)
from canterlot.models import UserModel
from canterlot.services import AuthService
from canterlot.use_cases import (
    ConfirmEmailVerificationUseCase,
    CreateSessionUseCase,
    RequestEmailVerificationUseCase,
    RequestPasswordResetUseCase,
    ResetPasswordUseCase,
    ValidatePasswordResetCodeUseCase,
)
from canterlot.utils import get_logger

from .cookies import (
    clear_password_reset_token_cookie,
    clear_refresh_token_cookie,
    set_password_reset_token_cookie,
    set_refresh_token_cookie,
)
from .dependencies.providers import (
    RefreshTokenContext,
    get_auth_service,
    get_confirm_email_verification_use_case,
    get_create_session_use_case,
    get_current_user,
    get_optional_current_user,
    get_optional_refresh_token_context,
    get_request_email_verification_use_case,
    get_request_password_reset_use_case,
    get_reset_password_use_case,
    get_user_from_reset_cookie,
    get_user_id_from_valid_refresh_token,
    get_validate_password_reset_code_use_case,
)
from .dependencies.rate_limiter import (
    rate_limit_email_verification_confirm_attempt,
    rate_limit_email_verification_request_attempt,
    rate_limit_login_attempt,
    rate_limit_password_reset_request_attempt,
    rate_limit_password_reset_validation_attempt,
    rate_limit_refresh_attempt,
)
from .responses import (
    CONFIRM_EMAIL_VERIFICATION_RESPONSES,
    CREATE_SESSION_RESPONSES,
    GET_RESET_SESSION_STATUS_RESPONSES,
    LOGOUT_RESPONSES,
    REQUEST_EMAIL_VERIFICATION_RESPONSES,
    REQUEST_PASSWORD_RESET_RESPONSES,
    RESET_PASSWORD_RESPONSES,
    ROTATE_SESSION_RESPONSES,
    VALIDATE_PASSWORD_RESET_CODE_RESPONSES,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/sessions",
    operation_id="createSession",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit_login_attempt)],
    responses=CREATE_SESSION_RESPONSES,
)
async def create_session(
    payload: CreateSessionRequest,
    response: Response,
    use_case: Annotated[CreateSessionUseCase, Depends(get_create_session_use_case)],
) -> AccessTokenResponse:
    result = await use_case.execute(payload)

    if result.is_new_user:
        response.status_code = status.HTTP_201_CREATED
        if result.location_header:
            response.headers["Location"] = result.location_header

    set_refresh_token_cookie(response, result.refresh_token)

    return AccessTokenResponse(access_token=result.access_token)


@router.post(
    "/login",
    include_in_schema=False,
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    result = await auth_service.login_user(
        username=form_data.username,
        plain_password=SecretStr(form_data.password),
    )
    set_refresh_token_cookie(response, result.refresh_token)
    return AccessTokenResponse(access_token=result.access_token)


@router.put(
    "/sessions/me",
    operation_id="rotateSession",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit_refresh_attempt)],
    responses=ROTATE_SESSION_RESPONSES,
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
    "/sessions/me",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=LOGOUT_RESPONSES,
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


@router.post(
    "/resets",
    operation_id="requestPasswordReset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset email",
    dependencies=[Depends(rate_limit_password_reset_request_attempt)],
    responses=REQUEST_PASSWORD_RESET_RESPONSES,
)
async def request_password_reset(
    payload: RequestPasswordResetRequest,
    use_case: Annotated[RequestPasswordResetUseCase, Depends(get_request_password_reset_use_case)],
) -> None:
    await use_case.execute(payload.identifier)


@router.post(
    "/resets/sessions",
    operation_id="validatePasswordResetCode",
    status_code=status.HTTP_200_OK,
    summary="Validate password reset verification code",
    dependencies=[Depends(rate_limit_password_reset_validation_attempt)],
    responses=VALIDATE_PASSWORD_RESET_CODE_RESPONSES,
)
async def validate_password_reset_code(
    payload: ValidatePasswordResetCodeRequest,
    response: Response,
    use_case: Annotated[ValidatePasswordResetCodeUseCase, Depends(get_validate_password_reset_code_use_case)],
) -> None:
    reset_token = await use_case.execute(payload)
    set_password_reset_token_cookie(response, reset_token)


@router.post(
    "/resets/sessions/me",
    operation_id="resetPassword",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Consume reset token and update password",
    responses=RESET_PASSWORD_RESPONSES,
)
async def reset_password(
    payload: ResetPasswordRequest,
    user: Annotated[UserModel, Depends(get_user_from_reset_cookie)],
    response: Response,
    use_case: Annotated[ResetPasswordUseCase, Depends(get_reset_password_use_case)],
) -> AccessTokenResponse:
    tokens = await use_case.execute(user, payload.new_password)

    clear_password_reset_token_cookie(response)
    set_refresh_token_cookie(response, tokens.refresh_token)

    return AccessTokenResponse(access_token=tokens.access_token)


@router.get(
    "/resets/sessions/me",
    operation_id="getResetSessionStatus",
    response_model=ResetSessionStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Check active password reset session state",
    responses=GET_RESET_SESSION_STATUS_RESPONSES,
)
async def get_reset_session_status(
    user: Annotated[UserModel, Depends(get_user_from_reset_cookie)],
) -> ResetSessionStatusResponse:
    is_creation = user.hashed_password is None

    return ResetSessionStatusResponse(is_creation=is_creation)


@router.post(
    "/verifications",
    operation_id="requestEmailVerification",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request email verification code",
    dependencies=[Depends(rate_limit_email_verification_request_attempt)],
    responses=REQUEST_EMAIL_VERIFICATION_RESPONSES,
)
async def request_email_verification(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[RequestEmailVerificationUseCase, Depends(get_request_email_verification_use_case)],
) -> None:
    await use_case.execute(user=current_user)


@router.put(
    "/verifications",
    operation_id="confirmEmailVerification",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm email verification",
    dependencies=[Depends(rate_limit_email_verification_confirm_attempt)],
    responses=CONFIRM_EMAIL_VERIFICATION_RESPONSES,
)
async def confirm_email_verification(
    payload: ConfirmEmailVerificationRequest,
    use_case: Annotated[ConfirmEmailVerificationUseCase, Depends(get_confirm_email_verification_use_case)],
    current_user: Annotated[UserModel | None, Depends(get_optional_current_user)] = None,
) -> None:
    await use_case.execute(payload=payload, current_user=current_user)
