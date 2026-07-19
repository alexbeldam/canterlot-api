from unittest.mock import AsyncMock

import pytest

from canterlot.gateways import BookProvider, LinkProvider
from canterlot.repositories import (
    BookRepository,
    CacheRepository,
    ClubRepository,
    InviteRepository,
    UserRepository,
)


@pytest.fixture
def user_repo() -> AsyncMock:
    return AsyncMock(spec=UserRepository)


@pytest.fixture
def club_repo() -> AsyncMock:
    return AsyncMock(spec=ClubRepository)


@pytest.fixture
def invite_repo() -> AsyncMock:
    return AsyncMock(spec=InviteRepository)


@pytest.fixture
def book_repo() -> AsyncMock:
    return AsyncMock(spec=BookRepository)


@pytest.fixture
def cache_repo() -> AsyncMock:
    return AsyncMock(spec=CacheRepository)


@pytest.fixture
def book_provider() -> AsyncMock:
    return AsyncMock(spec=BookProvider)


@pytest.fixture
def link_provider() -> AsyncMock:
    return AsyncMock(spec=LinkProvider)
