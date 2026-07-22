import re
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from beanie import PydanticObjectId
from curl_cffi.requests import AsyncSession
from fastapi.openapi.models import OAuth2
from fastapi.routing import iter_route_contexts
from pydantic import SecretStr

from canterlot.app import create_app
from canterlot.config import get_settings
from canterlot.exceptions import (
    GatewayConfigurationError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenMalformedError,
)
from canterlot.exceptions.auth import EmailNotVerifiedError
from canterlot.gateways import BookProvider, LinkProvider
from canterlot.gateways.auth.clients import GoogleAuthProvider
from canterlot.gateways.books.google import GoogleBookProvider
from canterlot.gateways.links.annas import AnnaLinkProvider
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.repositories import (
    BookRepository,
    CacheRepository,
    ClubRepository,
    DatabaseRepository,
    InviteRepository,
    UserRepository,
    VerificationRepository,
)
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieDatabaseRepository,
    BeanieInviteRepository,
    BeanieUserRepository,
    BeanieVerificationRepository,
)
from canterlot.repositories.redis import RedisRepository
from canterlot.routers.dependencies.providers import (
    LOGIN_PATH,
    RefreshTokenContext,
    _parse_subject_id,
    get_accept_invite_use_case,
    get_approve_pending_member_use_case,
    get_auth_service,
    get_book_from_identifier,
    get_book_id_from_identifier,
    get_book_providers,
    get_book_repository,
    get_book_service,
    get_cache_repository,
    get_catalog_service,
    get_change_member_role_use_case,
    get_change_password_use_case,
    get_club_from_slug,
    get_club_id_from_slug,
    get_club_repository,
    get_club_service,
    get_create_club_use_case,
    get_create_invite_use_case,
    get_create_password_use_case,
    get_create_session_use_case,
    get_curl_cffi_session,
    get_current_user,
    get_current_user_id,
    get_database_repositories,
    get_disconnect_auth_provider_use_case,
    get_dissolve_club_use_case,
    get_email_dispatch_service,
    get_email_task_queue,
    get_google_risc_verifier,
    get_health_service,
    get_invite_repository,
    get_invite_service,
    get_link_auth_provider_use_case,
    get_link_providers,
    get_oauth_providers,
    get_optional_refresh_token_context,
    get_rate_limiter,
    get_reclaim_club_ownership_use_case,
    get_redis_client,
    get_register_user_use_case,
    get_remove_club_member_use_case,
    get_resend_webhook_handler,
    get_revoke_auth_provider_use_case,
    get_transfer_club_ownership_use_case,
    get_user_from_username,
    get_user_id_from_username,
    get_user_id_from_valid_refresh_token,
    get_user_id_from_valid_reset_token,
    get_user_repository,
    get_user_service,
    get_verification_repository,
    get_verification_service,
    get_verified_user,
    get_verified_user_id,
    oauth2_scheme,
)
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
from canterlot.types import AuthProviderName
from canterlot.utils.security import (
    create_access_token,
    create_jwt_token,
    create_refresh_token,
    create_reset_token,
)

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


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
    async def it_returns_the_user_id_and_token_for_a_valid_refresh_token():
        token = create_refresh_token(SOME_USER_ID)

        result = await get_user_id_from_valid_refresh_token(token)

        assert result == RefreshTokenContext(user_id=SOME_USER_ID, token=token)

    async def it_raises_when_the_cookie_is_missing():
        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_refresh_token(None)

    async def it_raises_for_an_access_token_used_as_a_refresh_token():
        token = create_access_token(SOME_USER_ID)

        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_refresh_token(token)

    async def it_raises_token_expired_for_an_expired_refresh_token():
        token = create_jwt_token({"sub": str(SOME_USER_ID), "type": "refresh"}, timedelta(seconds=-1))

        with pytest.raises(TokenExpiredError):
            await get_user_id_from_valid_refresh_token(token)

    async def it_raises_token_malformed_for_a_garbage_token():
        with pytest.raises(TokenMalformedError):
            await get_user_id_from_valid_refresh_token("not.a.jwt")


def describe_get_optional_refresh_token_context():
    async def it_returns_the_context_for_a_valid_refresh_token():
        token = create_refresh_token(SOME_USER_ID)

        result = await get_optional_refresh_token_context(token)

        assert result == RefreshTokenContext(user_id=SOME_USER_ID, token=token)

    async def it_returns_none_when_the_cookie_is_missing():
        assert await get_optional_refresh_token_context(None) is None

    async def it_returns_none_for_an_access_token_used_as_a_refresh_token():
        token = create_access_token(SOME_USER_ID)

        assert await get_optional_refresh_token_context(token) is None

    async def it_returns_none_for_an_expired_refresh_token():
        token = create_jwt_token({"sub": str(SOME_USER_ID), "type": "refresh"}, timedelta(seconds=-1))

        assert await get_optional_refresh_token_context(token) is None

    async def it_returns_none_for_a_garbage_token():
        assert await get_optional_refresh_token_context("not.a.jwt") is None


def describe_get_user_id_from_valid_reset_token():
    async def it_returns_the_user_id_from_a_valid_reset_token():
        token = create_reset_token(SOME_USER_ID)
        assert await get_user_id_from_valid_reset_token(token) == SOME_USER_ID

    async def it_raises_when_reset_token_cookie_is_missing():
        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_reset_token(None)

    async def it_raises_when_non_reset_token_is_provided():
        access_token = create_access_token(SOME_USER_ID)
        with pytest.raises(InvalidCredentialsError):
            await get_user_id_from_valid_reset_token(access_token)


def describe_get_current_user():
    async def it_returns_the_user_when_found(user_service: AsyncMock):
        fake_user = SimpleNamespace(id=SOME_USER_ID)
        user_service.get_by_id.return_value = fake_user

        assert await get_current_user(SOME_USER_ID, user_service) is fake_user

    async def it_raises_when_the_user_no_longer_exists(user_service: AsyncMock):
        user_service.get_by_id.side_effect = InvalidCredentialsError("User not found")

        with pytest.raises(InvalidCredentialsError):
            await get_current_user(SOME_USER_ID, user_service)


def describe_verified_user_checks():
    async def it_resolves_verified_user_id(user_service: AsyncMock):
        user_service.is_verified_email.return_value = True
        assert await get_verified_user_id(SOME_USER_ID, user_service) == SOME_USER_ID

        user_service.is_verified_email.return_value = False
        with pytest.raises(EmailNotVerifiedError):
            await get_verified_user_id(SOME_USER_ID, user_service)

    async def it_resolves_verified_user_model():
        verified_user = MagicMock(spec=UserModel)
        verified_user.email_preferences.verified_at = "2026-01-01"
        assert await get_verified_user(verified_user) == verified_user

        unverified_user = MagicMock(spec=UserModel)
        unverified_user.email_preferences.verified_at = None
        with pytest.raises(EmailNotVerifiedError):
            await get_verified_user(unverified_user)


def describe_infrastructure_factories():
    async def it_returns_a_redis_client_and_email_task_queue(make_request):
        req = make_request()
        client = get_redis_client(req)
        assert client is not None
        assert get_email_task_queue(req) is not None

    async def it_yields_a_curl_cffi_session():
        session_gen = get_curl_cffi_session()
        session = await anext(session_gen)
        try:
            assert isinstance(session, AsyncSession)
        finally:
            await session_gen.aclose()


def describe_service_factories():
    def it_builds_a_redis_backed_cache_repository_and_rate_limiter():
        redis_mock = AsyncMock()
        assert isinstance(get_cache_repository(redis_mock), RedisRepository)
        assert isinstance(get_rate_limiter(redis_mock), RedisRepository)

    def it_builds_beanie_backed_repositories():
        assert isinstance(get_book_repository(), BeanieBookRepository)
        assert isinstance(get_club_repository(), BeanieClubRepository)
        assert isinstance(get_user_repository(), BeanieUserRepository)
        assert isinstance(get_invite_repository(), BeanieInviteRepository)
        assert isinstance(get_verification_repository(), BeanieVerificationRepository)

    def it_builds_the_database_repositories_used_for_health_checks():
        repos = get_database_repositories(AsyncMock())

        assert len(repos) == 2
        assert any(isinstance(repo, BeanieDatabaseRepository) for repo in repos)
        assert any(isinstance(repo, RedisRepository) for repo in repos)

    def it_builds_the_configured_book_providers(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings().gateways, "google_books_api_key", SecretStr("AIzaSy-test"))
        providers = get_book_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], GoogleBookProvider)

    async def it_builds_the_configured_link_providers():
        providers = await get_link_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], AnnaLinkProvider)

    def it_builds_the_configured_oauth_providers(monkeypatch: pytest.MonkeyPatch):
        gateways = get_settings().gateways
        monkeypatch.setattr(gateways, "google_oauth_client_id", "some-client-id")
        monkeypatch.setattr(gateways, "gravatar_oauth_client_id", None)
        monkeypatch.setattr(gateways, "gravatar_oauth_client_secret", None)

        providers = get_oauth_providers(AsyncMock(spec=AsyncSession))

        assert isinstance(providers[AuthProviderName.GOOGLE], GoogleAuthProvider)

    def it_returns_no_oauth_providers_when_none_are_configured(monkeypatch: pytest.MonkeyPatch):
        gateways = get_settings().gateways
        monkeypatch.setattr(gateways, "google_oauth_client_id", None)
        monkeypatch.setattr(gateways, "gravatar_oauth_client_id", None)
        monkeypatch.setattr(gateways, "gravatar_oauth_client_secret", None)

        assert get_oauth_providers(AsyncMock(spec=AsyncSession)) == {}

    def it_raises_error_when_google_risc_is_not_configured(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings().gateways, "google_oauth_client_id", None)
        expected = re.escape("Google RISC event verification is not configured.")

        with pytest.raises(GatewayConfigurationError, match=expected):
            get_google_risc_verifier(AsyncMock(spec=AsyncSession))

    def it_builds_google_risc_verifier_when_configured(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings().gateways, "google_oauth_client_id", "some-client-id")
        verifier = get_google_risc_verifier(AsyncMock(spec=AsyncSession))
        assert verifier is not None

    async def it_raises_error_when_resend_webhook_is_not_configured(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings().email, "resend_api_key", None)
        monkeypatch.setattr(get_settings().email, "resend_webhook_secret", None)
        expected = re.escape("Resend webhook is not configured.")

        with pytest.raises(GatewayConfigurationError, match=expected):
            await get_resend_webhook_handler(AsyncMock(), AsyncMock())

    async def it_builds_resend_webhook_handler_when_configured(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(get_settings().email, "resend_api_key", SecretStr("test-key"))
        monkeypatch.setattr(get_settings().email, "resend_webhook_secret", SecretStr("test-secret"))
        handler = await get_resend_webhook_handler(AsyncMock(), AsyncMock())
        assert handler is not None


def describe_slug_username_and_identifier_resolvers():
    async def it_resolves_club_id_and_club_from_slug():
        club_service = AsyncMock(spec=ClubService)
        club_id = PydanticObjectId()
        club_model = MagicMock(spec=ClubModel)

        club_service.get_club_id_by_slug.return_value = club_id
        club_service.get_club_by_slug.return_value = club_model

        assert await get_club_id_from_slug("my-club", club_service) == club_id
        assert await get_club_from_slug("my-club", club_service) == club_model

    async def it_resolves_user_id_and_user_from_username():
        user_service = AsyncMock(spec=UserService)
        user_id = PydanticObjectId()
        user_model = MagicMock(spec=UserModel)

        user_service.get_id_by_username.return_value = user_id
        user_service.get_by_username.return_value = user_model

        assert await get_user_id_from_username("twilight", user_service) == user_id
        assert await get_user_from_username("twilight", user_service) == user_model

    async def it_resolves_book_id_and_book_from_identifier():
        book_service = AsyncMock(spec=BookService)
        book_id = PydanticObjectId()
        book_model = MagicMock()

        book_service.get_book_id_by_identifier.return_value = book_id
        book_service.get_book_by_identifier.return_value = book_model

        assert await get_book_id_from_identifier("9783161484100", book_service) == book_id
        assert await get_book_from_identifier("9783161484100", book_service) == book_model


def describe_service_factories_real():
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
            user_repo=AsyncMock(spec=UserRepository),
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

    async def it_builds_a_user_service():
        service = await get_user_service(
            user_repo=AsyncMock(spec=UserRepository),
            cache_repo=AsyncMock(spec=CacheRepository),
        )
        assert isinstance(service, UserService)

    async def it_builds_an_email_dispatch_service():
        service = await get_email_dispatch_service(
            email_task_queue=AsyncMock(),
            cache_repo=AsyncMock(spec=CacheRepository),
        )
        assert isinstance(service, EmailDispatchService)

    async def it_builds_a_verification_service():
        service = await get_verification_service(
            repo=AsyncMock(spec=VerificationRepository),
        )
        assert isinstance(service, VerificationService)

    async def it_builds_a_health_service():
        service = await get_health_service(database_repos=[AsyncMock(spec=DatabaseRepository)])
        assert isinstance(service, HealthService)


def describe_use_case_factories():
    async def it_instantiates_all_use_cases():
        s = AsyncMock()

        assert await get_create_invite_use_case(s, s, s) is not None
        assert await get_create_session_use_case(s, s, s) is not None
        assert await get_register_user_use_case(s, s, s, s, s) is not None
        assert await get_accept_invite_use_case(s, s) is not None
        assert await get_create_club_use_case(s, s) is not None
        assert await get_change_password_use_case(s, s) is not None
        assert await get_create_password_use_case(s, s) is not None
        assert await get_link_auth_provider_use_case(s, s) is not None
        assert await get_disconnect_auth_provider_use_case(s, s) is not None
        assert await get_transfer_club_ownership_use_case(s, s, s) is not None
        assert await get_reclaim_club_ownership_use_case(s, s, s) is not None
        assert await get_approve_pending_member_use_case(s, s) is not None
        assert await get_change_member_role_use_case(s, s) is not None
        assert await get_remove_club_member_use_case(s, s) is not None
        assert await get_dissolve_club_use_case(s, s, s) is not None
        assert await get_revoke_auth_provider_use_case(s, s) is not None


def describe_oauth2_scheme():
    def it_points_at_a_real_registered_post_route():
        app = create_app()

        model = cast(OAuth2, oauth2_scheme.model)
        assert model.flows.password is not None
        assert model.flows.password.tokenUrl == LOGIN_PATH

        matching_routes = [ctx for ctx in iter_route_contexts(app.routes) if ctx.path == LOGIN_PATH]

        assert matching_routes, f"no route registered at {LOGIN_PATH}"
        assert any("POST" in (ctx.methods or set()) for ctx in matching_routes)
