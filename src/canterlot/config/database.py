import importlib
import pkgutil

from beanie import Document, init_beanie
from pymongo import AsyncMongoClient

from canterlot import models
from canterlot.utils import get_logger

from .settings import settings

logger = get_logger(__name__)


def discover_beanie_models() -> list[type[Document]]:
    discovered_models = []

    for _, module_name, is_pkg in pkgutil.walk_packages(models.__path__, models.__name__ + "."):
        if not is_pkg:
            module = importlib.import_module(module_name)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Document)
                    and attr is not Document
                    and attr not in discovered_models
                ):
                    discovered_models.append(attr)

    return discovered_models


class DatabaseManager:
    def __init__(self) -> None:
        self.__client: AsyncMongoClient | None = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def open(self):
        self.__client = AsyncMongoClient(settings.mongodb_url, maxPoolSize=10, minPoolSize=2, tz_aware=True)
        database = self.__client[settings.mongodb_db_name]

        all_models = discover_beanie_models()
        await init_beanie(database=database, document_models=all_models)
        logger.info("Connected to MongoDB pool.")

    async def close(self):
        if self.__client:
            await self.__client.close()
            logger.info("Closed MongoDB connections.")
