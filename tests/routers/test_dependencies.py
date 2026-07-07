from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from curl_cffi.requests import AsyncSession

from canterlot.config import get_settings
from canterlot.exceptions import InvalidCredentialsError, TokenExpiredError, TokenMalformedError
from canterlot.models.enums import AuthProviderName
from canterlot.providers import BookProvider, GoogleBookProvider, LinkProvider
from canterlot.providers.annas import AnnaLinkProvider
from canterlot.providers.auth import GoogleAuthProvider
from canterlot.repositories import BookRepository, CacheRepository, ClubRepository, InviteRepository, UserRepository
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieInviteRepository,
    BeanieUserRepository,
)
from canterlot.repositories.redis import RedisCacheRepository
from canterlot.routers.dependencies import (
    _parse_subject_id,
    get_auth_service,
    get_book_providers,
    get_book_repository,
    get_book_service,
    get_cache_repository,
    get_catalog_service,
    get_club_repository,
    get_club_service,
    get_curl_cffi_session,
    get_current_user,
    get_current_user_id,
    get_invite_repository,
    get_invite_service,
    get_link_providers,
    get_oauth_providers,
    get_redis_client,
    get_user_id_from_valid_refresh_token,
    get_user_repository,
)
from canterlot.services import AuthService, BookService, CatalogService, ClubService, InviteService
from canterlot.utils.security import create_access_token, create_jwt_token, create_refresh_token

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def user_repo() -> AsyncMock:
    return AsyncMock(spec=UserRepository)


def describe_parse_subject_id():
    def it_parses_a_valid_object_id_string():
        assert _parse_subject_id(str(SOME_USER_ID)) == SOME_USER_ID

    def it_raises_invalid_credentials_for_a_malformed_id():
        with pytest.raises(InvalidCredentialsError):
            _parse_subject_id("not-a-valid-object-id")


def describe_get_current_user_id():
    async def it_returns_the_user_id_from_a_valid_access_token():
        token = create_access_token(SOME_USER_ID)

        assert await get_current_user_id(token) == SOME_USER_ID

    async def it_raises_for_a_token_missing_the_subject_claim():
        token = create_jwt_token({"type": "access"}, timedelta(minutes=5))

        with pytest.raises(InvalidCredentialsError):
            await get_current_user_id(token)

    async def it_raises_for_a_refresh_token_used_as_an_access_token():
        token = create_refresh_token(SOME_USER_ID)

        with pytest.raises(InvalidCredentialsError):
            await get_current_user_id(token)

    async def it_raises_token_expired_for_an_expired_token():
        token = create_jwt_token({"sub": str(SOME_USER_ID), "type": "access"}, timedelta(seconds=-1))

        with pytest.raises(TokenExpiredError):
            await get_current_user_id(token)

    async def it_raises_token_malformed_for_a_garbage_token():
        with pytest.raises(TokenMalformedError):
            await get_current_user_id("not.a.jwt")


def describe_get_user_id_from_valid_refresh_token():
    async def it_returns_the_user_id_and_token_for_a_valid_refresh_token(user_repo: AsyncMock):
        token = create_refresh_token(SOME_USER_ID)
        user_repo.find_by_id.return_value = SimpleNamespace(refresh_tokens=[token])

        result = await get_user_id_from_valid_refresh_token(token, user_repo)

        assert result == (SOME_USER_ID, token)

    async def it_raises_for_an_access_token_used_as_a_refresh_token(user_repo: AsyncMock):
        token = create_access_token(SOME_USER_ID)

        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_refresh_token(token, user_repo)

        user_repo.find_by_id.assert_not_called()

    async def it_raises_when_the_user_no_longer_exists(user_repo: AsyncMock):
        token = create_refresh_token(SOME_USER_ID)
        user_repo.find_by_id.return_value = None

        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_refresh_token(token, user_repo)

    async def it_raises_when_the_refresh_token_has_been_revoked(user_repo: AsyncMock):
        token = create_refresh_token(SOME_USER_ID)
        user_repo.find_by_id.return_value = SimpleNamespace(refresh_tokens=["some-other-token"])

        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_refresh_token(token, user_repo)


def describe_get_current_user():
    async def it_returns_the_user_when_found(user_repo: AsyncMock):
        fake_user = SimpleNamespace(id=SOME_USER_ID)
        user_repo.find_by_id.return_value = fake_user

        assert await get_current_user(SOME_USER_ID, user_repo) is fake_user

    async def it_raises_when_the_user_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None

        with pytest.raises(InvalidCredentialsError):
            await get_current_user(SOME_USER_ID, user_repo)


def describe_infrastructure_factories():
    async def it_yields_a_redis_client():
        client_gen = get_redis_client()
        client = await anext(client_gen)
        try:
            assert client is not None
        finally:
            await client_gen.aclose()

    async def it_yields_a_curl_cffi_session():
        session_gen = get_curl_cffi_session()
        session = await anext(session_gen)
        try:
            assert isinstance(session, AsyncSession)
        finally:
            await session_gen.aclose()

    def it_builds_a_redis_backed_cache_repository():
        assert isinstance(get_cache_repository(AsyncMock()), RedisCacheRepository)

    def it_builds_beanie_backed_repositories():
        assert isinstance(get_book_repository(), BeanieBookRepository)
        assert isinstance(get_club_repository(), BeanieClubRepository)
        assert isinstance(get_user_repository(), BeanieUserRepository)
        assert isinstance(get_invite_repository(), BeanieInviteRepository)

    def it_builds_the_configured_book_providers():
        providers = get_book_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], GoogleBookProvider)

    async def it_builds_the_configured_link_providers():
        providers = await get_link_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], AnnaLinkProvider)

    def it_builds_the_configured_oauth_providers(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", "some-client-id")

        providers = get_oauth_providers()

        assert isinstance(providers[AuthProviderName.GOOGLE], GoogleAuthProvider)

    def it_returns_no_oauth_providers_when_none_are_configured():
        assert get_oauth_providers() == {}


def describe_service_factories():
    async def it_builds_a_book_service():
        service = await get_book_service(
            cache=AsyncMock(spec=CacheRepository),
            book_repo=AsyncMock(spec=BookRepository),
            providers=[AsyncMock(spec=BookProvider)],
        )
        assert isinstance(service, BookService)

    async def it_builds_a_catalog_service():
        service = await get_catalog_service(
            book_repo=AsyncMock(spec=BookRepository),
            club_repo=AsyncMock(spec=ClubRepository),
            link_providers=[AsyncMock(spec=LinkProvider)],
        )
        assert isinstance(service, CatalogService)

    async def it_builds_an_auth_service():
        service = await get_auth_service(user_repo=AsyncMock(spec=UserRepository), oauth_providers={})
        assert isinstance(service, AuthService)

    async def it_builds_a_club_service():
        service = await get_club_service(
            club_repo=AsyncMock(spec=ClubRepository),
            user_repo=AsyncMock(spec=UserRepository),
        )
        assert isinstance(service, ClubService)

    async def it_builds_an_invite_service():
        service = await get_invite_service(
            invite_repo=AsyncMock(spec=InviteRepository),
            club_repo=AsyncMock(spec=ClubRepository),
            user_repo=AsyncMock(spec=UserRepository),
        )
        assert isinstance(service, InviteService)
