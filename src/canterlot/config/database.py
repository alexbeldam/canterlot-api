from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from canterlot.models import BEANIE_DOCUMENT_MODELS
from canterlot.utils import get_logger

from .settings import get_settings

logger = get_logger(__name__)


class DatabaseManager:
    def __init__(self) -> None:
        self.__client: AsyncMongoClient | None = None
        self.__database: AsyncDatabase | None = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def open(self):
        settings = get_settings().db
        self.__client = AsyncMongoClient(
            settings.mongodb_url.get_secret_value(),
            maxPoolSize=10,
            minPoolSize=2,
            tz_aware=True,
        )
        self.__database = self.__client[settings.mongodb_db_name]

        await init_beanie(database=self.__database, document_models=BEANIE_DOCUMENT_MODELS)
        logger.info("Connected to MongoDB pool.")

    async def reinitialize_beanie(self) -> None:
        if self.__database is None:
            raise RuntimeError("DatabaseManager is not open.")

        await init_beanie(database=self.__database, document_models=BEANIE_DOCUMENT_MODELS)
        logger.info("Beanie reinitialized.")

    async def close(self):
        if self.__client:
            await self.__client.close()
            logger.info("Closed MongoDB connections.")
