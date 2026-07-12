from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as aioredis
from beanie import PydanticObjectId
from bson.errors import InvalidId
from curl_cffi.requests import AsyncSession
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from canterlot.config import get_settings
from canterlot.exceptions import ClubNotFoundError, InvalidCredentialsError, RateLimitExceededError
from canterlot.exceptions.book import BookNotFoundError
from canterlot.exceptions.user import UserNotFoundError
from canterlot.models import UserModel
from canterlot.models.book import BookExternalId
from canterlot.models.club import ClubSlugStr
from canterlot.models.enums import AuthProviderName
from canterlot.models.user import UsernameStr
from canterlot.providers import BookProvider, LinkProvider, get_all_book_providers, get_all_link_providers
from canterlot.providers.auth import OAuthProvider, get_all_oauth_providers
from canterlot.repositories import BookRepository, CacheRepository, ClubRepository, InviteRepository, UserRepository
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieInviteRepository,
    BeanieUserRepository,
)
from canterlot.repositories.redis import RedisCacheRepository
from canterlot.services import AuthService, BookService, CatalogService, ClubService, InviteService, UserService
from canterlot.utils import decode_jwt_payload
from canterlot.utils.format import ISBNStr

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_redis_client() -> AsyncGenerator[aioredis.Redis]:
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def get_curl_cffi_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(
        timeout=(4.0, 20.0),
        impersonate="chrome",
    ) as session:
        yield session


def get_cache_repository(redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)]) -> CacheRepository:
    return RedisCacheRepository(redis_client)


def get_book_repository() -> BookRepository:
    return BeanieBookRepository()


def get_club_repository() -> ClubRepository:
    return BeanieClubRepository()


def get_user_repository() -> UserRepository:
    return BeanieUserRepository()


def get_invite_repository() -> InviteRepository:
    return BeanieInviteRepository()


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


def get_oauth_providers() -> dict[AuthProviderName, OAuthProvider]:
    return get_all_oauth_providers()


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


async def get_user_service(user_repo: Annotated[UserRepository, Depends(get_user_repository)]):
    return UserService(user_repo)


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


@dataclass(frozen=True, slots=True)
class RefreshTokenContext:
    user_id: PydanticObjectId
    token: str


async def get_user_id_from_valid_refresh_token(
    token: Annotated[str, Depends(oauth2_scheme)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> RefreshTokenContext:
    payload = decode_jwt_payload(token)

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if user_id is None or token_type != "refresh":
        raise InvalidCredentialsError("Invalid session refresh payload structure.")

    pyid = _parse_subject_id(user_id)
    refresh_tokens = await user_repo.find_refresh_tokens_by_id(pyid)
    if refresh_tokens is None or token not in refresh_tokens:
        raise InvalidCredentialsError("This refresh token has been revoked or invalidated.")

    return RefreshTokenContext(user_id=pyid, token=token)


async def get_current_user(
    user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserModel:
    user = await user_repo.find_by_id(user_id)
    if user is None:
        raise InvalidCredentialsError("Authenticated user profile record no longer exists.")
    return user


async def _enforce_rate_limit(redis_client: aioredis.Redis, key: str, limit: int, window_seconds: int) -> None:
    count = await redis_client.incr(key)
    await redis_client.expire(key, window_seconds, nx=True)
    if count > limit:
        ttl = await redis_client.ttl(key)
        raise RateLimitExceededError(ttl if ttl > 0 else window_seconds)


def rate_limit_club_owner_action(scope: str):
    async def dependency(
        club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
        current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
        redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)],
    ) -> None:
        settings = get_settings()
        await _enforce_rate_limit(
            redis_client,
            key=f"ratelimit:{scope}:{club_id}:{current_user_id}",
            limit=settings.club_ownership_action_rate_limit,
            window_seconds=settings.club_ownership_action_rate_limit_window_seconds,
        )

    return dependency
