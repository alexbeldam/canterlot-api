from collections.abc import Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.app import create_app
from canterlot.repositories import BookRepository, ClubRepository, UserRepository
from canterlot.routers.dependencies import (
    RefreshTokenContext,
    get_auth_service,
    get_book_repository,
    get_book_service,
    get_catalog_service,
    get_club_repository,
    get_club_service,
    get_current_user,
    get_current_user_id,
    get_health_service,
    get_invite_service,
    get_optional_refresh_token_context,
    get_redis_client,
    get_user_id_from_valid_refresh_token,
    get_user_repository,
    get_user_service,
)
from canterlot.services import (
    AuthService,
    BookService,
    CatalogService,
    ClubService,
    HealthService,
    InviteService,
    UserService,
)

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def auth_service() -> AsyncMock:
    return AsyncMock(spec=AuthService)


@pytest.fixture
def book_service() -> AsyncMock:
    return AsyncMock(spec=BookService)


@pytest.fixture
def catalog_service() -> AsyncMock:
    return AsyncMock(spec=CatalogService)


@pytest.fixture
def club_service() -> AsyncMock:
    return AsyncMock(spec=ClubService)


@pytest.fixture
def invite_service() -> AsyncMock:
    return AsyncMock(spec=InviteService)


@pytest.fixture
def user_service() -> AsyncMock:
    return AsyncMock(spec=UserService)


@pytest.fixture
def health_service() -> AsyncMock:
    return AsyncMock(spec=HealthService)


@pytest.fixture
def club_repo() -> AsyncMock:
    return AsyncMock(spec=ClubRepository)


@pytest.fixture
def user_repo() -> AsyncMock:
    return AsyncMock(spec=UserRepository)


@pytest.fixture
def book_repo() -> AsyncMock:
    return AsyncMock(spec=BookRepository)


@pytest.fixture
def current_user() -> SimpleNamespace:
    return SimpleNamespace(id=SOME_USER_ID, email="alice@example.com", username="alice_1")


@pytest.fixture
def redis_client() -> AsyncMock:
    mock = AsyncMock()
    mock.incr.return_value = 1
    mock.ttl.return_value = -1
    return mock


@pytest.fixture
def client(
    auth_service: AsyncMock,
    book_service: AsyncMock,
    catalog_service: AsyncMock,
    club_service: AsyncMock,
    invite_service: AsyncMock,
    user_service: AsyncMock,
    health_service: AsyncMock,
    club_repo: AsyncMock,
    user_repo: AsyncMock,
    book_repo: AsyncMock,
    current_user: SimpleNamespace,
    redis_client: AsyncMock,
) -> Iterator[TestClient]:
    app = create_app()

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan

    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_book_service] = lambda: book_service
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[get_club_service] = lambda: club_service
    app.dependency_overrides[get_invite_service] = lambda: invite_service
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_health_service] = lambda: health_service
    app.dependency_overrides[get_club_repository] = lambda: club_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_book_repository] = lambda: book_repo
    app.dependency_overrides[get_current_user_id] = lambda: current_user.id
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    app.dependency_overrides[get_user_id_from_valid_refresh_token] = lambda: RefreshTokenContext(
        user_id=current_user.id, token="old-refresh-token"
    )
    app.dependency_overrides[get_optional_refresh_token_context] = lambda: RefreshTokenContext(
        user_id=current_user.id, token="old-refresh-token"
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
