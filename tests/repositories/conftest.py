import pathlib
import re
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from pymongo import AsyncMongoClient
from testcontainers.community.redis import AsyncRedisContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from canterlot.config.bootstrap import bootstrap_beanie
from canterlot.models import BEANIE_DOCUMENT_MODELS

_THIS_DIR = pathlib.Path(__file__).parent
_DB_NAME = "canterlot_integration_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[DockerContainer]:
    # MongoDbContainer forces root auth, which --replSet then needs a keyfile for; a raw container avoids that.
    container = (
        DockerContainer("mongo:6.0")
        .with_command("mongod --replSet rs0 --bind_ip_all")
        .with_exposed_ports(27017)
        .waiting_for(LogMessageWaitStrategy(re.compile(r"waiting for connections", re.IGNORECASE)))
    )
    with container:
        yield container



async def _wait_for_connectable(client: AsyncMongoClient) -> None:
    for _ in range(30):
        try:
            await client.admin.command("ping")
            return
        except (AutoReconnect, OperationFailure):
            await asyncio.sleep(1)
    raise RuntimeError("mongod never became connectable")


async def _initiate_replica_set(url: str) -> None:
    probe_client: AsyncMongoClient = AsyncMongoClient(
        url,
        directConnection=True,
        serverSelectionTimeoutMS=30_000,
    )

    try:
        await _wait_for_connectable(probe_client)

        try:
            await probe_client.admin.command("replSetGetStatus")
            return
        except OperationFailure as e:
            if e.code != _REPL_SET_NOT_YET_INITIALIZED:
                raise

        await probe_client.admin.command(
            "replSetInitiate",
            {
                "_id": "rs0",
                "members": [
                    {
                        "_id": 0,
                        "host": "localhost:27017",
                    }
                ],
            },
        )

        # Give MongoDB time to transition from STARTUP to PRIMARY.
        await asyncio.sleep(2)

        for _ in range(60):
            try:
                status = await probe_client.admin.command("replSetGetStatus")

                if status["myState"] == 1:
                    return

            except OperationFailure as e:
                if e.code != _REPL_SET_NOT_YET_INITIALIZED:
                    raise

            await asyncio.sleep(1)

        raise RuntimeError("mongod replica set never reached PRIMARY state")

    finally:
        await probe_client.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _beanie_client(mongodb_container: DockerContainer) -> AsyncIterator[AsyncMongoClient]:
    host = mongodb_container.get_container_host_ip()
    port = mongodb_container.get_exposed_port(27017)
    # directConnection=True: the node advertises itself as "localhost:27017", not the Docker-mapped port.
    url = f"mongodb://{host}:{port}/?directConnection=true"

    client: AsyncMongoClient = AsyncMongoClient(url, tz_aware=True)
    try:
        await bootstrap_beanie(
            url,
            client[_DB_NAME],
            BEANIE_DOCUMENT_MODELS,
            replica_set_member_host="localhost:27017",
        )
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
