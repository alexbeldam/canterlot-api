import redis.asyncio as aioredis
from redis.exceptions import RedisError

from canterlot.repositories import CacheRepository, DatabaseRepository


class RedisRepository(CacheRepository, DatabaseRepository):
    def __init__(self, redis_client: aioredis.Redis):
        self.__redis = redis_client

    async def find(self, key: str) -> str | None:
        raw = await self.__redis.get(key)

        return raw if isinstance(raw, (str | None)) else raw.decode("utf-8")

    async def save(self, key: str, value: str, expire_seconds: int) -> None:
        await self.__redis.set(key, value, ex=expire_seconds)

    async def ping(self) -> bool:
        try:
            return bool(await self.__redis.ping())
        except RedisError:
            return False
