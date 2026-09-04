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
        payload = {"field": "some-value"}
        await redis_repo.save("some-key", payload, expire_seconds=60)

        assert await redis_repo.find("some-key") == payload

    async def it_returns_none_for_a_missing_key(redis_repo: RedisRepository):
        assert await redis_repo.find("does-not-exist") is None


def describe_find_many():
    async def it_returns_empty_list_for_empty_keys(redis_repo: RedisRepository):
        assert await redis_repo.find_many([]) == []

    async def it_retrieves_multiple_keys_in_batch(redis_repo: RedisRepository):
        key1, payload1 = "batch-key-1", {"field": "val1"}
        key2, payload2 = "batch-key-2", {"field": "val2"}

        await redis_repo.save(key1, payload1, expire_seconds=60)
        await redis_repo.save(key2, payload2, expire_seconds=60)

        results = await redis_repo.find_many([key1, "missing-key", key2])

        assert results == [payload1, None, payload2]


def describe_invalidate():
    async def it_deletes_a_stored_key(redis_repo: RedisRepository):
        key = "delete-me"
        await redis_repo.save(key, {"field": "value"}, expire_seconds=60)
        assert await redis_repo.find(key) is not None

        await redis_repo.invalidate(key)

        assert await redis_repo.find(key) is None


def describe_expiry():
    async def it_sets_a_ttl_on_the_stored_key(redis_repo: RedisRepository, _redis_client: aioredis.Redis):
        await redis_repo.save("ttl-key", {"field": "value"}, expire_seconds=60)

        ttl = await _redis_client.ttl("ttl-key")

        assert 0 < ttl <= 60


def describe_ping():
    async def it_returns_true_when_redis_is_reachable(redis_repo: RedisRepository):
        assert await redis_repo.ping() is True

    async def it_returns_false_when_redis_is_unreachable():
        unreachable_client = AsyncMock(spec=aioredis.Redis)
        unreachable_client.ping.side_effect = RedisError("connection refused")

        assert await RedisRepository(unreachable_client).ping() is False


def describe_rate_limiter_evaluate():
    async def it_returns_none_when_under_rate_limit(redis_repo: RedisRepository):
        key = "rate-limit-pass"

        # Allowed up to 2 calls in 60s
        res1 = await redis_repo.evaluate(key, limit=2, window_seconds=60)
        res2 = await redis_repo.evaluate(key, limit=2, window_seconds=60)

        assert res1 is None
        assert res2 is None

    async def it_returns_ttl_when_rate_limit_exceeded(redis_repo: RedisRepository):
        key = "rate-limit-exceed"

        # Limit is 1, so second hit fails
        await redis_repo.evaluate(key, limit=1, window_seconds=60)
        retry_after = await redis_repo.evaluate(key, limit=1, window_seconds=60)

        assert retry_after is not None
        assert 0 < retry_after <= 60
