import pathlib
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from beanie import init_beanie
from pymongo import AsyncMongoClient
from testcontainers.community.redis import AsyncRedisContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HealthcheckWaitStrategy

from canterlot.models import BEANIE_DOCUMENT_MODELS

_THIS_DIR = pathlib.Path(__file__).parent
_DB_NAME = "canterlot_integration_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[DockerContainer]:
    # A raw container, not MongoDbContainer, since that helper wraps community mongo's env-var scheme,
    # not mongodb-atlas-local's.
    container = (
        DockerContainer("mongodb/mongodb-atlas-local:8.0")
        .with_exposed_ports(27017)
        .waiting_for(HealthcheckWaitStrategy())
    )
    with container:
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _beanie_client(mongodb_container: DockerContainer) -> AsyncIterator[AsyncMongoClient]:
    host = mongodb_container.get_container_host_ip()
    port = mongodb_container.get_exposed_port(27017)
    # directConnection=True: the node advertises itself as "localhost:27017", not the Docker-mapped port.
    url = f"mongodb://{host}:{port}/?directConnection=true"

    client: AsyncMongoClient = AsyncMongoClient(url, tz_aware=True)
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
    # "localhost" hangs on some dual-stack Windows setups that resolve it to ::1 first; 127.0.0.1 avoids that.
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
