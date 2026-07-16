from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from canterlot.repositories.redis import RedisRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def redis_repo(_redis_client: aioredis.Redis) -> RedisRepository:
    return RedisRepository(_redis_client)


def describe_save_and_find():
    async def it_persists_and_returns_a_value(redis_repo: RedisRepository):
        await redis_repo.save("some-key", "some-value", expire_seconds=60)

        assert await redis_repo.find("some-key") == "some-value"

    async def it_returns_none_for_a_missing_key(redis_repo: RedisRepository):
        assert await redis_repo.find("does-not-exist") is None


def describe_expiry():
    async def it_sets_a_ttl_on_the_stored_key(redis_repo: RedisRepository, _redis_client: aioredis.Redis):
        await redis_repo.save("ttl-key", "value", expire_seconds=60)

        ttl = await _redis_client.ttl("ttl-key")

        assert 0 < ttl <= 60


def describe_ping():
    async def it_returns_true_when_redis_is_reachable(redis_repo: RedisRepository):
        assert await redis_repo.ping() is True

    async def it_returns_false_when_redis_is_unreachable():
        unreachable_client = AsyncMock(spec=aioredis.Redis)
        unreachable_client.ping.side_effect = RedisError("connection refused")

        assert await RedisRepository(unreachable_client).ping() is False
