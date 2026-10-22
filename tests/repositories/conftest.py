from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from testcontainers.community.redis import AsyncRedisContainer

from tests.mongo_integration import current_worker_id, init_hoodied_beanie  # noqa: F401


def _redis_db_index() -> int:
    worker_id = current_worker_id()
    # Redis's default config allows 16 logical dbs (0-15) - comfortably above any realistic
    # xdist worker count. "master" (no xdist) and "gw0" never run concurrently, so both
    # safely mapping to db 0 is fine.
    return 0 if worker_id == "master" else int(worker_id.removeprefix("gw"))


@pytest.fixture(scope="session")
def redis_container() -> Iterator[AsyncRedisContainer]:
    with AsyncRedisContainer("redis:7.0-alpine") as container:  # matches docker-compose.yml's pinned version
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _redis_client(redis_container: AsyncRedisContainer) -> AsyncIterator[aioredis.Redis]:
    # "localhost" hangs on some dual-stack Windows setups that resolve it to ::1 first; 127.0.0.1 avoids that.
    port = redis_container.get_exposed_port(redis_container.port)
    client: aioredis.Redis = aioredis.Redis(host="127.0.0.1", port=port, db=_redis_db_index(), decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _flushed_redis(_redis_client: aioredis.Redis) -> AsyncIterator[None]:
    yield
    await _redis_client.flushdb()
