import os
import random
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import bcrypt
import mongomock.database
import pytest
import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient
from polyfactory.factories.base import BaseFactory
from saq import Queue

from canterlot.config import get_settings
from canterlot.config.enums import Environment
from canterlot.emails import EmailTemplate
from canterlot.models import BEANIE_DOCUMENT_MODELS
from canterlot.repositories import (
    BookRepository,
    CacheRepository,
    ClubRepository,
    InviteRepository,
    UserRepository,
    VerificationRepository,
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

_original_list_collection_names = mongomock.database.Database.list_collection_names
_original_gensalt = bcrypt.gensalt

bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _original_gensalt(4, prefix)  # noqa: ARG005

_FAKE_SETTINGS_ENV = {
    "ENVIRONMENT": Environment.TEST,
    "AUTH__JWT_SECRET_KEY": "test-jwt-secret-key-that-is-at-least-32-bytes-long",
    "DB__MONGODB_URL": "mongodb://localhost:27017/",
    "DB__MONGODB_DB_NAME": "canterlot_test",
    "DB__REDIS_URL": "redis://localhost:6379/0",
}


def _list_collection_names_ignoring_unsupported_kwargs(self, filter=None, session=None, **_kwargs):
    return _original_list_collection_names(self, filter=filter, session=session)


@pytest.fixture(autouse=True, scope="session")
def _fake_settings() -> Iterator[None]:
    old_env = os.environ.copy()

    os.environ.update(_FAKE_SETTINGS_ENV)
    get_settings.cache_clear()

    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _beanie_client() -> AsyncIterator[AsyncMongoMockClient]:
    mongomock.database.Database.list_collection_names = (  # type: ignore[method-assign]
        _list_collection_names_ignoring_unsupported_kwargs
    )

    client: AsyncMongoMockClient = AsyncMongoMockClient()

    try:
        await init_beanie(
            database=client["test"],  # type: ignore[arg-type]
            document_models=BEANIE_DOCUMENT_MODELS,
        )
        yield client
    finally:
        client.close()
        mongomock.database.Database.list_collection_names = _original_list_collection_names  # type: ignore[method-assign]


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _initialized_beanie(_beanie_client: AsyncMongoMockClient) -> AsyncIterator[None]:
    yield
    for model in BEANIE_DOCUMENT_MODELS:
        await model.delete_all()


# ========================================================
# Shared Infra Mocks
# ========================================================


@pytest.fixture
def email_task_queue() -> AsyncMock:
    return AsyncMock(spec=Queue)


# ========================================================
# Shared Repository Mocks
# ========================================================


@pytest.fixture
def user_repo() -> AsyncMock:
    repo = AsyncMock(spec=UserRepository)
    repo.exists_by_username.return_value = False
    repo.exists_by_email.return_value = False
    repo.set_delivery_failed_by_email.return_value = False
    return repo


@pytest.fixture
def club_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClubRepository)
    repo.exists_by_club_slug.return_value = False
    return repo


@pytest.fixture
def book_repo() -> AsyncMock:
    return AsyncMock(spec=BookRepository)


@pytest.fixture
def invite_repo() -> AsyncMock:
    return AsyncMock(spec=InviteRepository)


@pytest.fixture
def cache_repo() -> AsyncMock:
    repo = AsyncMock(spec=CacheRepository)
    repo.find = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    repo.invalidate = AsyncMock()

    return repo


@pytest.fixture
def verification_repo() -> AsyncMock:
    return AsyncMock(spec=VerificationRepository)


# ========================================================
# Shared Service Mocks
# ========================================================


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
def email_dispatch_service() -> AsyncMock:
    return AsyncMock(spec=EmailDispatchService)


@pytest.fixture
def verification_service() -> AsyncMock:
    return AsyncMock(spec=VerificationService)


@pytest.fixture
def health_service() -> AsyncMock:
    return AsyncMock(spec=HealthService)


# ========================================================
# Template Helper Fixtures
# ========================================================


@pytest.fixture
def random_template() -> EmailTemplate[Any]:
    """Returns a random registered EmailTemplate instance."""
    return random.choice(EmailTemplate.all())


@pytest.fixture
def global_template() -> EmailTemplate:
    """Returns an arbitrary registered GlobalEmailTemplate."""
    from canterlot.emails.core.definitions import GlobalEmailTemplate

    return next(t for t in EmailTemplate.all() if isinstance(t, GlobalEmailTemplate))


@pytest.fixture
def club_template() -> EmailTemplate:
    """Returns an arbitrary registered ClubPreferenceEmailTemplate (non-global)."""
    from canterlot.emails.core.definitions import ClubPreferenceEmailTemplate, GlobalEmailTemplate

    return next(
        t
        for t in EmailTemplate.all()
        if isinstance(t, ClubPreferenceEmailTemplate) and not isinstance(t, GlobalEmailTemplate)
    )


@pytest.fixture
def engagement_template() -> EmailTemplate:
    """Returns an arbitrary registered ENGAGEMENT category template."""
    from canterlot.emails.core.definitions import ClubPreferenceEmailTemplate, EmailCategory

    return next(
        t
        for t in EmailTemplate.all()
        if t.category == EmailCategory.ENGAGEMENT and isinstance(t, ClubPreferenceEmailTemplate)
    )


@pytest.fixture
def transactional_template() -> EmailTemplate:
    """Returns an arbitrary registered TRANSACTIONAL category template."""
    from canterlot.emails.core.definitions import EmailCategory, GlobalEmailTemplate

    return next(
        t
        for t in EmailTemplate.all()
        if t.category == EmailCategory.TRANSACTIONAL and isinstance(t, GlobalEmailTemplate)
    )


@pytest.fixture
def template_with_formatted_subject() -> EmailTemplate[Any]:
    """Returns a registered EmailTemplate whose subject contains string formatting placeholders."""
    formatted_template = next(
        (t for t in EmailTemplate.all() if "{" in t.subject_template and "}" in t.subject_template),
        None,
    )
    if not formatted_template:
        pytest.skip("No registered EmailTemplate has dynamic subject formatting placeholders.")
    return formatted_template


# ========================================================
# Polyfactory Settings
# ========================================================


@pytest.fixture(autouse=True, scope="session")
def _seed_polyfactory() -> None:
    """Seeds the global Faker instance so test data generation is reproducible."""
    BaseFactory.__faker__.seed_instance(23)
