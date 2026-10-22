import structlog
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .exceptions import DatabaseManagerNotOpenError
from .lifecycle import init_hoodie, reset_hoodie
from .polling import HoodiePollingConfig

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Owns the Mongo client for the process and runs `init_hoodie` against its database.

    Usable as an async context manager (`async with DatabaseManager(...)`), which calls
    `open()` on entry and `close()` on exit. Every `Entity` subclass must already be imported
    when `open()` runs.

    :param mongodb_url: the Mongo connection string.
    :type mongodb_url: str
    :param mongodb_db_name: the name of the database to initialize.
    :type mongodb_db_name: str
    :param polling: the search-sync/index-build polling config to apply, or None to keep the
        currently active one.
    :type polling: HoodiePollingConfig | None
    """

    def __init__(
        self,
        mongodb_url: str,
        mongodb_db_name: str,
        *,
        polling: HoodiePollingConfig | None = None,
    ) -> None:
        self.__mongodb_url = mongodb_url
        self.__mongodb_db_name = mongodb_db_name
        self.__polling = polling
        self.__client: AsyncMongoClient | None = None
        self.__database: AsyncDatabase | None = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def open(self):
        """Connects to Mongo and initializes Beanie and the search indexes for every registered
        Entity (see `init_hoodie`).

        :raises SearchIndexNeverQueryableError: if an index never becomes queryable within the
            polling window.
        """
        self.__client = AsyncMongoClient(
            self.__mongodb_url,
            maxPoolSize=10,
            minPoolSize=2,
            tz_aware=True,
        )
        self.__database = self.__client[self.__mongodb_db_name]

        await init_hoodie(self.__database, polling=self.__polling)
        logger.info("Connected to MongoDB pool.")

    async def reset(self) -> None:
        """Drops every registered Entity's collection and rebuilds them and their search indexes
        (see `reset_hoodie`).

        :raises DatabaseManagerNotOpenError: if the manager isn't open.
        :raises SearchIndexNeverQueryableError: if search is enabled and a rebuilt index never
            becomes queryable within the polling window.
        """
        if self.__database is None:
            raise DatabaseManagerNotOpenError

        await reset_hoodie(self.__database)
        logger.info("Database reset.")

    async def close(self):
        """Closes the Mongo client. Safe to call when the manager isn't open."""
        if self.__client:
            await self.__client.close()
            self.__client = None
            self.__database = None
            logger.info("Closed MongoDB connections.")
