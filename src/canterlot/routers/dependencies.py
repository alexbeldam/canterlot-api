from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as aioredis
from beanie import PydanticObjectId
from bson.errors import InvalidId
from curl_cffi.requests import AsyncSession
from fastapi import Cookie, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from saq import Queue

from canterlot.config import get_settings
from canterlot.constants import (
    CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE,
    LOGIN_ACCOUNT_RATELIMIT_TEMPLATE,
    LOGIN_IP_RATELIMIT_TEMPLATE,
    OAUTH_SIGNIN_RATELIMIT_TEMPLATE,
    REFRESH_RATELIMIT_TEMPLATE,
    REGISTER_RATELIMIT_TEMPLATE,
)
from canterlot.dto.auth import CreateSessionRequest
from canterlot.emails.webhooks import ResendWebhookHandler
from canterlot.exceptions import (
    ClubNotFoundError,
    GatewayConfigurationError,
    InvalidCredentialsError,
    RateLimitExceededError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.exceptions.auth import EmailNotVerifiedError
from canterlot.exceptions.book import BookNotFoundError
from canterlot.exceptions.user import UserNotFoundError
from canterlot.gateways import (
    BookProvider,
    LinkProvider,
    get_all_book_providers,
    get_all_link_providers,
)
from canterlot.gateways.auth import OAuthProvider, get_all_oauth_providers
from canterlot.gateways.auth.risc import GoogleRiscVerifier
from canterlot.models import UserModel
from canterlot.models.book import BookExternalId
from canterlot.models.club import ClubSlugStr
from canterlot.models.user import UsernameStr
from canterlot.repositories import (
    BookRepository,
    CacheRepository,
    ClubRepository,
    DatabaseRepository,
    InviteRepository,
    UserRepository,
)
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieDatabaseRepository,
    BeanieInviteRepository,
    BeanieUserRepository,
)
from canterlot.repositories.interfaces import RateLimiter
from canterlot.repositories.redis import RedisRepository
from canterlot.routers.cookies import REFRESH_TOKEN_COOKIE_NAME
from canterlot.services import (
    AuthService,
    BookService,
    CatalogService,
    ClubService,
    HealthService,
    InviteService,
    UserService,
)
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import AuthProviderName, ISBNStr, SessionType
from canterlot.utils import decode_jwt_payload

LOGIN_PATH = "/v1/auth/login"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=LOGIN_PATH)


def get_redis_client(request: Request) -> aioredis.Redis:
    return request.app.state.redis_client


def get_email_task_queue(request: Request) -> Queue:
    return request.app.state.email_task_queue


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
    providers: Annotated[list[BookProvider], Depends(get_book_providers)],
) -> BookService:
    return BookService(cache=cache, book_repo=book_repo, providers=providers)


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

    if not settings.resend_api_key or not settings.resend_webhook_secret:
        raise GatewayConfigurationError("Resend webhook is not configured.")

    return ResendWebhookHandler(
        cache_repo=cache_repo,
        user_repo=user_repo,
        resend_api_key=settings.resend_api_key,
        resend_webhook_secret=settings.resend_webhook_secret,
    )


def get_oauth_providers(
    session: Annotated[AsyncSession, Depends(get_curl_cffi_session)],
) -> dict[AuthProviderName, OAuthProvider]:
    return get_all_oauth_providers(session)


def get_google_risc_verifier(
    session: Annotated[AsyncSession, Depends(get_curl_cffi_session)],
) -> GoogleRiscVerifier:
    client_id = get_settings().google_oauth_client_id

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
):
    return ClubService(club_repo, user_repo)


async def get_invite_service(
    invite_repo: Annotated[InviteRepository, Depends(get_invite_repository)],
    club_repo: Annotated[ClubRepository, Depends(get_club_repository)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    return InviteService(invite_repo, club_repo, user_repo)


async def get_user_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    cache_repo: Annotated[CacheRepository, Depends(get_cache_repository)],
) -> UserService:
    return UserService(user_repo, cache_repo)


async def get_email_dispatch_service(
    email_task_queue: Annotated[Queue, Depends(get_email_task_queue)],
    cache_repo: Annotated[CacheRepository, Depends(get_cache_repository)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> EmailDispatchService:
    return EmailDispatchService(
        saq_queue=email_task_queue,
        cache_repo=cache_repo,
        user_service=user_service,
    )


async def get_health_service(
    database_repos: Annotated[list[DatabaseRepository], Depends(get_database_repositories)],
) -> HealthService:
    return HealthService(database_repos)


async def get_club_id_from_slug(
    club_slug: ClubSlugStr,
    club_repo: Annotated[ClubRepository, Depends(get_club_repository)],
) -> PydanticObjectId:
    club_id = await club_repo.find_id_by_slug(club_slug)
    if club_id is None:
        raise ClubNotFoundError(f"Club with slug '{club_slug}' not found")
    return club_id


async def get_user_id_from_username(
    username: UsernameStr,
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> PydanticObjectId:
    user_id = await user_repo.find_id_by_username(username)
    if user_id is None:
        raise UserNotFoundError(f"User with username '{username}' not found")
    return user_id


async def get_book_id_from_identifier(
    identifier: BookExternalId | ISBNStr,
    book_repo: Annotated[BookRepository, Depends(get_book_repository)],
) -> PydanticObjectId:
    id = await book_repo.find_id_by_identifier(identifier)
    if id is None:
        raise BookNotFoundError(f"Book with identifier '{identifier}' not found")
    return id


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

    if user_id is None or token_type != "access":
        raise InvalidCredentialsError("Could not validate credentials structure.")

    return _parse_subject_id(user_id)


async def require_verified_email(
    user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> None:
    is_verified = await user_repo.is_email_verified_by_id(user_id)

    if not is_verified:
        raise EmailNotVerifiedError("Email address is not verified.")


@dataclass(frozen=True, slots=True)
class RefreshTokenContext:
    user_id: PydanticObjectId
    token: str


def _decode_refresh_token(token: str) -> RefreshTokenContext:
    payload = decode_jwt_payload(token)

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if user_id is None or token_type != "refresh":
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


async def get_current_user(
    user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserModel:
    user = await user_repo.find_by_id(user_id)
    if user is None:
        raise InvalidCredentialsError("Authenticated user profile record no longer exists.")
    return user


async def _enforce_rate_limit(rate_limiter: RateLimiter, key: str, limit: int, window_seconds: int) -> None:
    ttl = await rate_limiter.evaluate(key, limit, window_seconds)

    if ttl:
        raise RateLimitExceededError(ttl)


def rate_limit_club_owner_action(scope: str):
    async def dependency(
        club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
        current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        settings = get_settings()
        key = CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE.format(scope=scope, club_id=club_id, user_id=current_user_id)
        await _enforce_rate_limit(
            rate_limiter,
            key=key,
            limit=settings.club_ownership_action_rate_limit,
            window_seconds=settings.club_ownership_action_rate_limit_window_seconds,
        )

    return dependency


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def rate_limit_register_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings()
    await _enforce_rate_limit(
        rate_limiter,
        key=REGISTER_RATELIMIT_TEMPLATE.format(ip=_client_ip(request)),
        limit=settings.auth_register_rate_limit,
        window_seconds=settings.auth_register_rate_limit_window_seconds,
    )


async def rate_limit_refresh_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings()
    await _enforce_rate_limit(
        rate_limiter,
        key=REFRESH_RATELIMIT_TEMPLATE.format(ip=_client_ip(request)),
        limit=settings.auth_refresh_rate_limit,
        window_seconds=settings.auth_refresh_rate_limit_window_seconds,
    )


async def rate_limit_login_attempt(
    request: Request,
    payload: CreateSessionRequest,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings()
    ip = _client_ip(request)

    if payload.type is SessionType.OAUTH:
        await _enforce_rate_limit(
            rate_limiter,
            key=OAUTH_SIGNIN_RATELIMIT_TEMPLATE.format(ip=ip),
            limit=settings.auth_oauth_signin_rate_limit,
            window_seconds=settings.auth_oauth_signin_rate_limit_window_seconds,
        )
        return

    await _enforce_rate_limit(
        rate_limiter,
        key=LOGIN_IP_RATELIMIT_TEMPLATE.format(ip=ip),
        limit=settings.auth_login_ip_rate_limit,
        window_seconds=settings.auth_login_rate_limit_window_seconds,
    )
    await _enforce_rate_limit(
        rate_limiter,
        key=LOGIN_ACCOUNT_RATELIMIT_TEMPLATE.format(username=payload.username),
        limit=settings.auth_login_account_rate_limit,
        window_seconds=settings.auth_login_rate_limit_window_seconds,
    )
