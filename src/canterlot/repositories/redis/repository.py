from collections.abc import Mapping
from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from canterlot.repositories import CacheRepository, DatabaseRepository, RateLimiter
from canterlot.utils import get_logger

logger = get_logger(__name__)


class RedisRepository(CacheRepository, DatabaseRepository, RateLimiter):
    def __init__(self, redis_client: aioredis.Redis):
        self.__redis = redis_client

    async def find(self, key: str) -> dict[str, str] | None:
        raw_dict = await self.__redis.hgetall(key)

        if not raw_dict:
            return None

        return {
            k.decode("utf-8") if isinstance(k, bytes) else k: v.decode("utf-8") if isinstance(v, bytes) else v
            for k, v in raw_dict.items()
        }

    async def save(self, key: str, mapping: Mapping[str, str | int | float], expire_seconds: int) -> None:
        async with self.__redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=cast(Any, mapping))
            pipe.expire(key, expire_seconds)
            await pipe.execute()

    async def invalidate(self, key: str) -> None:
        await self.__redis.delete(key)

    async def ping(self) -> bool:
        try:
            return bool(await self.__redis.ping())
        except RedisError:
            return False

    async def evaluate(self, key: str, limit: int, window_seconds: int) -> int | None:
        async with self.__redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = await pipe.execute()

        if count > limit:
            ttl = await self.__redis.ttl(key)
            return ttl if ttl > 0 else window_seconds

        return None
