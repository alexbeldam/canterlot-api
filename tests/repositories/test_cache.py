import pytest
import redis.asyncio as aioredis

from canterlot.repositories.redis.cache import RedisCacheRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def cache_repo(_redis_client: aioredis.Redis) -> RedisCacheRepository:
    return RedisCacheRepository(_redis_client)


def describe_save_and_find():
    async def it_persists_and_returns_a_value(cache_repo: RedisCacheRepository):
        await cache_repo.save("some-key", "some-value", expire_seconds=60)

        assert await cache_repo.find("some-key") == "some-value"

    async def it_returns_none_for_a_missing_key(cache_repo: RedisCacheRepository):
        assert await cache_repo.find("does-not-exist") is None


def describe_expiry():
    async def it_sets_a_ttl_on_the_stored_key(cache_repo: RedisCacheRepository, _redis_client: aioredis.Redis):
        await cache_repo.save("ttl-key", "value", expire_seconds=60)

        ttl = await _redis_client.ttl("ttl-key")

        assert 0 < ttl <= 60
