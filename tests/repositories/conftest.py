import pathlib
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from beanie import init_beanie
from pymongo import AsyncMongoClient
from testcontainers.mongodb import MongoDbContainer
from testcontainers.redis import AsyncRedisContainer

from canterlot.models import BEANIE_DOCUMENT_MODELS

_THIS_DIR = pathlib.Path(__file__).parent
_DB_NAME = "canterlot_integration_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[MongoDbContainer]:
    with MongoDbContainer("mongo:6.0") as container:
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _beanie_client(mongodb_container: MongoDbContainer) -> AsyncIterator[AsyncMongoClient]:
    client: AsyncMongoClient = AsyncMongoClient(mongodb_container.get_connection_url())
    try:
        await init_beanie(database=client[_DB_NAME], document_models=BEANIE_DOCUMENT_MODELS)
        yield client
    finally:
        await client.drop_database(_DB_NAME)
        await client.close()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _initialized_beanie(_beanie_client: AsyncMongoClient) -> AsyncIterator[None]:
    yield
    for model in BEANIE_DOCUMENT_MODELS:
        await model.delete_all()


@pytest.fixture(scope="session")
def redis_container() -> Iterator[AsyncRedisContainer]:
    with AsyncRedisContainer("redis:7.0-alpine") as container:  # matches docker-compose.yml's pinned version
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _redis_client(redis_container: AsyncRedisContainer) -> AsyncIterator[aioredis.Redis]:
    # get_async_client() resolves the host as the literal string "localhost", which some
    # dual-stack Windows setups resolve to ::1 first and then hang instead of falling back
    # to IPv4 -- 127.0.0.1 avoids that resolution step entirely.
    port = redis_container.get_exposed_port(redis_container.port)
    client: aioredis.Redis = aioredis.Redis(host="127.0.0.1", port=port, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _flushed_redis(_redis_client: aioredis.Redis) -> AsyncIterator[None]:
    yield
    await _redis_client.flushdb()
