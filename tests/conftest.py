import os
from collections.abc import AsyncIterator, Iterator

import bcrypt
import mongomock.database
import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from canterlot.config.settings import get_settings
from canterlot.models import BEANIE_DOCUMENT_MODELS

_original_list_collection_names = mongomock.database.Database.list_collection_names
_original_gensalt = bcrypt.gensalt

bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _original_gensalt(rounds, prefix)

_FAKE_SETTINGS_ENV = {
    "GOOGLE_BOOKS_API_KEY": "test-google-books-api-key",
    "JWT_SECRET_KEY": "test-jwt-secret-key-that-is-at-least-32-bytes-long",
    "JWT_ALGORITHM": "HS256",
    "MONGODB_URL": "mongodb://localhost:27017/",
    "MONGODB_DB_NAME": "canterlot_test",
    "REDIS_URL": "redis://localhost:6379/0",
}


def _list_collection_names_ignoring_unsupported_kwargs(self, filter=None, session=None, **_kwargs):
    return _original_list_collection_names(self, filter=filter, session=session)


@pytest.fixture(autouse=True, scope="session")
def _fake_settings() -> Iterator[None]:
    previous_values = {key: os.environ.get(key) for key in _FAKE_SETTINGS_ENV}
    os.environ.update(_FAKE_SETTINGS_ENV)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in previous_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _initialized_beanie() -> AsyncIterator[None]:
    mongomock.database.Database.list_collection_names = (  # type: ignore[method-assign]
        _list_collection_names_ignoring_unsupported_kwargs
    )
    try:
        client: AsyncMongoMockClient = AsyncMongoMockClient()
        await init_beanie(
            database=client["test"],  # type: ignore[arg-type]
            document_models=BEANIE_DOCUMENT_MODELS,
        )
        yield
    finally:
        mongomock.database.Database.list_collection_names = _original_list_collection_names  # type: ignore[method-assign]
