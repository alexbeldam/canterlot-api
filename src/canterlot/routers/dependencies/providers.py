from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, cast

import redis.asyncio as aioredis
from beanie import PydanticObjectId
from bson.errors import InvalidId
from curl_cffi.requests import AsyncSession
from fastapi import Cookie, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from saq import Queue

from canterlot.config import get_settings
from canterlot.emails.webhooks import ResendWebhookHandler
from canterlot.exceptions import (
    GatewayConfigurationError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.exceptions.auth import EmailNotVerifiedError
from canterlot.gateways import (
    BookProvider,
    LinkProvider,
    get_all_book_providers,
    get_all_link_providers,
)
from canterlot.gateways.auth import OAuthProvider, get_all_oauth_providers
from canterlot.gateways.auth.risc import GoogleRiscVerifier
from canterlot.models import BookModel, ClubModel, UserModel
from canterlot.repositories import (
    BookRepository,
    CacheRepository,
    ClubRepository,
    DatabaseRepository,
    InviteRepository,
    RateLimiter,
    ReadBookRepository,
    UserRepository,
    VerificationRepository,
)
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieDatabaseRepository,
    BeanieInviteRepository,
    BeanieReadBookRepository,
    BeanieUserRepository,
    BeanieVerificationRepository,
)
from canterlot.repositories.redis import RedisRepository
from canterlot.routers.cookies import PASSWORD_RESET_TOKEN_COOKIE_NAME, REFRESH_TOKEN_COOKIE_NAME
from canterlot.services import (
    AuthService,
    BookService,
    CatalogService,
    ClubService,
    EmailDispatchService,
    HealthService,
    InviteService,
    UserService,
    VerificationService,
)
from canterlot.types import AuthProviderName, BookExternalId, ClubSlugStr, ISBNStr, TokenType, UsernameStr
from canterlot.use_cases import (
    AcceptInviteUseCase,
    ApprovePendingMemberUseCase,
    ChangeMemberRoleUseCase,
    ChangePasswordUseCase,
    ConfirmEmailVerificationUseCase,
    CreateClubUseCase,
    CreateInviteUseCase,
    CreatePasswordUseCase,
    CreateSessionUseCase,
    DisconnectAuthProviderUseCase,
    DissolveClubUseCase,
    LinkAuthProviderUseCase,
    ProcessUnsubscribeUseCase,
    ReclaimClubOwnershipUseCase,
    RegisterUserUseCase,
    RemoveClubMemberUseCase,
    RequestEmailVerificationUseCase,
    RequestPasswordResetUseCase,
    ResetPasswordUseCase,
    RevokeAuthProviderUseCase,
    TransferClubOwnershipUseCase,
    ValidatePasswordResetCodeUseCase,
)
from canterlot.utils import decode_jwt_payload

LOGIN_PATH = "/v1/auth/login"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=LOGIN_PATH)


def get_redis_client(request: Request) -> aioredis.Redis:
    return cast(aioredis.Redis, request.app.state.redis_client)


def get_email_task_queue(request: Request) -> Queue:
    return cast(Queue, request.app.state.email_task_queue)


async def get_curl_cffi_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(
        timeout=(4.0, 20.0),
        impersonate="chrome",
    ) as session:
        yield session


def get_cache_repository(redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)]) -> CacheRepository:
    return RedisRepository(redis_client)


def get_rate_limiter(redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)]) -> RateLimiter:
    return RedisRepository(redis_client)


def get_book_repository() -> BookRepository:
    return BeanieBookRepository()


def get_club_repository() -> ClubRepository:
    return BeanieClubRepository()


def get_user_repository() -> UserRepository:
    return BeanieUserRepository()


def get_invite_repository() -> InviteRepository:
    return BeanieInviteRepository()


def get_verification_repository() -> VerificationRepository:
    return BeanieVerificationRepository()


def get_read_book_repository() -> ReadBookRepository:
    return BeanieReadBookRepository()


def get_database_repositories(
    redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)],
) -> list[DatabaseRepository]:
    return [BeanieDatabaseRepository(), RedisRepository(redis_client)]


def get_book_providers(session: Annotated[AsyncSession, Depends(get_curl_cffi_session)]) -> list[BookProvider]:
    return get_all_book_providers(session)


async def get_link_providers(session: Annotated[AsyncSession, Depends(get_curl_cffi_session)]) -> list[LinkProvider]:
    return get_all_link_providers(session)


async def get_book_service(
    cache: Annotated[CacheRepository, Depends(get_cache_repository)],
    book_repo: Annotated[BookRepository, Depends(get_book_repository)],
    read_book_repo: Annotated[ReadBookRepository, Depends(get_read_book_repository)],
    providers: Annotated[list[BookProvider], Depends(get_book_providers)],
) -> BookService:
    return BookService(cache=cache, book_repo=book_repo, read_book_repo=read_book_repo, providers=providers)


async def get_catalog_service(
    book_repo: Annotated[BookRepository, Depends(get_book_repository)],
    club_repo: Annotated[ClubRepository, Depends(get_club_repository)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    link_providers: Annotated[list[LinkProvider], Depends(get_link_providers)],
) -> CatalogService:
    return CatalogService(book_repo=book_repo, club_repo=club_repo, user_repo=user_repo, link_providers=link_providers)


async def get_resend_webhook_handler(
    cache_repo: Annotated[CacheRepository, Depends(get_cache_repository)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> ResendWebhookHandler:
    settings = get_settings()

    if not settings.email.resend_api_key or not settings.email.resend_webhook_secret:
        raise GatewayConfigurationError("Resend webhook is not configured.")

    return ResendWebhookHandler(
        cache_repo=cache_repo,
        user_repo=user_repo,
        resend_api_key=settings.email.resend_api_key.get_secret_value(),
        resend_webhook_secret=settings.email.resend_webhook_secret.get_secret_value(),
    )


def get_oauth_providers(
    session: Annotated[AsyncSession, Depends(get_curl_cffi_session)],
) -> dict[AuthProviderName, OAuthProvider]:
    return get_all_oauth_providers(session)


def get_google_risc_verifier(
    session: Annotated[AsyncSession, Depends(get_curl_cffi_session)],
) -> GoogleRiscVerifier:
    client_id = get_settings().gateways.google_oauth_client_id

    if not client_id:
        raise GatewayConfigurationError("Google RISC event verification is not configured.")

    return GoogleRiscVerifier(client_id, session)


async def get_auth_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    oauth_providers: Annotated[dict[AuthProviderName, OAuthProvider], Depends(get_oauth_providers)],
) -> AuthService:
    return AuthService(user_repo, oauth_providers)


async def get_club_service(
    club_repo: Annotated[ClubRepository, Depends(get_club_repository)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    book_repo: Annotated[BookRepository, Depends(get_book_repository)],
    read_book_repo: Annotated[ReadBookRepository, Depends(get_read_book_repository)],
):
    return ClubService(club_repo, user_repo, book_repo, read_book_repo)


async def get_invite_service(
    invite_repo: Annotated[InviteRepository, Depends(get_invite_repository)],
    club_repo: Annotated[ClubRepository, Depends(get_club_repository)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    return InviteService(invite_repo, club_repo, user_repo)


async def get_user_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    cache_repo: Annotated[CacheRepository, Depends(get_cache_repository)],
    read_book_repo: Annotated[ReadBookRepository, Depends(get_read_book_repository)],
    book_repo: Annotated[BookRepository, Depends(get_book_repository)],
) -> UserService:
    return UserService(user_repo, cache_repo, read_book_repo, book_repo)


async def get_email_dispatch_service(
    email_task_queue: Annotated[Queue, Depends(get_email_task_queue)],
    cache_repo: Annotated[CacheRepository, Depends(get_cache_repository)],
) -> EmailDispatchService:
    return EmailDispatchService(saq_queue=email_task_queue, cache_repo=cache_repo)


async def get_verification_service(
    repo: Annotated[VerificationRepository, Depends(get_verification_repository)],
) -> VerificationService:
    return VerificationService(repo)


async def get_health_service(
    database_repos: Annotated[list[DatabaseRepository], Depends(get_database_repositories)],
) -> HealthService:
    return HealthService(database_repos)


async def get_club_id_from_slug(
    club_slug: ClubSlugStr,
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> PydanticObjectId:
    return await club_service.get_club_id_by_slug(club_slug)


async def get_club_from_slug(
    club_slug: ClubSlugStr,
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> ClubModel:
    return await club_service.get_club_by_slug(club_slug)


async def get_user_id_from_username(
    username: UsernameStr,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> PydanticObjectId:
    return await user_service.get_id_by_username(username)


async def get_user_from_username(
    username: UsernameStr,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserModel:
    return await user_service.get_by_username(username)


async def get_book_id_from_identifier(
    identifier: BookExternalId | ISBNStr,
    book_service: Annotated[BookService, Depends(get_book_service)],
) -> PydanticObjectId:
    return await book_service.get_book_id_by_identifier(identifier)


async def get_book_from_identifier(
    identifier: BookExternalId | ISBNStr,
    book_service: Annotated[BookService, Depends(get_book_service)],
) -> BookModel:
    return await book_service.get_book_by_identifier(identifier)


def _parse_subject_id(user_id: str) -> PydanticObjectId:
    try:
        return PydanticObjectId(user_id)
    except InvalidId:
        raise InvalidCredentialsError("Could not validate credentials structure.") from None


async def get_current_user_id(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> PydanticObjectId:
    payload = decode_jwt_payload(token)

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if user_id is None or token_type != TokenType.ACCESS:
        raise InvalidCredentialsError("Could not validate credentials structure.")

    return _parse_subject_id(user_id)


async def get_optional_current_user_id(
    token: Annotated[str | None, Depends(OAuth2PasswordBearer(tokenUrl=LOGIN_PATH, auto_error=False))],
) -> PydanticObjectId | None:
    if token is None:
        return None

    try:
        payload = decode_jwt_payload(token)
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")

        if user_id is None or token_type != TokenType.ACCESS:
            return None

        return _parse_subject_id(user_id)
    except (TokenExpiredError, TokenMalformedError, InvalidCredentialsError):
        return None


async def get_verified_user_id(
    user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> PydanticObjectId:
    verified = await user_service.is_verified_email(user_id)

    if not verified:
        raise EmailNotVerifiedError("Email address is not verified.")

    return user_id


@dataclass(frozen=True, slots=True)
class RefreshTokenContext:
    user_id: PydanticObjectId
    token: str


def _decode_refresh_token(token: str) -> RefreshTokenContext:
    payload = decode_jwt_payload(token)

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if user_id is None or token_type != TokenType.REFRESH:
        raise InvalidCredentialsError("Invalid session refresh payload structure.")

    return RefreshTokenContext(user_id=_parse_subject_id(user_id), token=token)


async def get_user_id_from_valid_refresh_token(
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE_NAME)] = None,
) -> RefreshTokenContext:
    if refresh_token is None:
        raise InvalidCredentialsError("Invalid session refresh payload structure.")

    return _decode_refresh_token(refresh_token)


async def get_optional_refresh_token_context(
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE_NAME)] = None,
) -> RefreshTokenContext | None:
    if refresh_token is None:
        return None

    try:
        return _decode_refresh_token(refresh_token)
    except (TokenExpiredError, TokenMalformedError, InvalidCredentialsError):
        return None


async def get_user_id_from_valid_reset_token(
    reset_token: Annotated[str | None, Cookie(alias=PASSWORD_RESET_TOKEN_COOKIE_NAME)] = None,
) -> PydanticObjectId:
    if reset_token is None:
        raise InvalidCredentialsError("Invalid password reset payload structure.")

    payload = decode_jwt_payload(reset_token)

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if user_id is None or token_type != TokenType.RESET:
        raise InvalidCredentialsError("Invalid password reset payload structure.")

    return _parse_subject_id(user_id)


async def get_user_from_reset_cookie(
    user_id: Annotated[PydanticObjectId, Depends(get_user_id_from_valid_reset_token)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserModel:
    return await user_service.get_by_id(user_id)


async def get_current_user(
    user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserModel:
    return await user_service.get_by_id(user_id)


async def get_optional_current_user(
    user_id: Annotated[PydanticObjectId | None, Depends(get_optional_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserModel | None:
    if user_id is None:
        return None

    return await user_service.find_by_id(user_id)


async def get_verified_user(user: Annotated[UserModel, Depends(get_current_user)]) -> UserModel:
    if not user.email_preferences.verified_at:
        raise EmailNotVerifiedError("Email address is not verified.")
    return user


async def get_create_invite_use_case(
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> CreateInviteUseCase:
    return CreateInviteUseCase(invite_service, user_service, email_dispatch)


async def get_create_session_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> CreateSessionUseCase:
    return CreateSessionUseCase(
        auth_service=auth_service,
        invite_service=invite_service,
        email_dispatch=email_dispatch,
    )


async def get_register_user_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
    verification_service: Annotated[VerificationService, Depends(get_verification_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> RegisterUserUseCase:
    return RegisterUserUseCase(
        auth_service=auth_service,
        invite_service=invite_service,
        club_service=club_service,
        verification_service=verification_service,
        email_dispatch=email_dispatch,
    )


async def get_accept_invite_use_case(
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
) -> AcceptInviteUseCase:
    return AcceptInviteUseCase(
        invite_service=invite_service,
        club_service=club_service,
    )


async def get_create_club_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
) -> CreateClubUseCase:
    return CreateClubUseCase(
        club_service=club_service,
        invite_service=invite_service,
    )


async def get_change_password_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_create_password_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> CreatePasswordUseCase:
    return CreatePasswordUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_link_auth_provider_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> LinkAuthProviderUseCase:
    return LinkAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_disconnect_auth_provider_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> DisconnectAuthProviderUseCase:
    return DisconnectAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_transfer_club_ownership_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> TransferClubOwnershipUseCase:
    return TransferClubOwnershipUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch,
    )


async def get_reclaim_club_ownership_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> ReclaimClubOwnershipUseCase:
    return ReclaimClubOwnershipUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch,
    )


async def get_approve_pending_member_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> ApprovePendingMemberUseCase:
    return ApprovePendingMemberUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch,
    )


async def get_change_member_role_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> ChangeMemberRoleUseCase:
    return ChangeMemberRoleUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch,
    )


async def get_remove_club_member_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> RemoveClubMemberUseCase:
    return RemoveClubMemberUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch,
    )


async def get_dissolve_club_use_case(
    club_service: Annotated[ClubService, Depends(get_club_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> DissolveClubUseCase:
    return DissolveClubUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch,
    )


async def get_revoke_auth_provider_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> RevokeAuthProviderUseCase:
    return RevokeAuthProviderUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_process_unsubscribe_use_case(
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> ProcessUnsubscribeUseCase:
    return ProcessUnsubscribeUseCase(user_service=user_service)


async def get_request_password_reset_use_case(
    user_service: Annotated[UserService, Depends(get_user_service)],
    verification_service: Annotated[VerificationService, Depends(get_verification_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> RequestPasswordResetUseCase:
    return RequestPasswordResetUseCase(
        user_service=user_service,
        verification_service=verification_service,
        email_dispatch=email_dispatch,
    )


async def get_validate_password_reset_code_use_case(
    user_service: Annotated[UserService, Depends(get_user_service)],
    verification_service: Annotated[VerificationService, Depends(get_verification_service)],
) -> ValidatePasswordResetCodeUseCase:
    return ValidatePasswordResetCodeUseCase(
        user_service=user_service,
        verification_service=verification_service,
    )


async def get_reset_password_use_case(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> ResetPasswordUseCase:
    return ResetPasswordUseCase(
        auth_service=auth_service,
        email_dispatch=email_dispatch,
    )


async def get_request_email_verification_use_case(
    verification_service: Annotated[VerificationService, Depends(get_verification_service)],
    email_dispatch: Annotated[EmailDispatchService, Depends(get_email_dispatch_service)],
) -> RequestEmailVerificationUseCase:
    return RequestEmailVerificationUseCase(
        verification_service=verification_service,
        email_dispatch=email_dispatch,
    )


async def get_confirm_email_verification_use_case(
    verification_service: Annotated[VerificationService, Depends(get_verification_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> ConfirmEmailVerificationUseCase:
    return ConfirmEmailVerificationUseCase(
        verification_service=verification_service,
        user_service=user_service,
    )
