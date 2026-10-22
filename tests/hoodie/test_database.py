from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from canterlot.hoodie import DatabaseManager, DatabaseManagerNotOpenError, HoodiePollingConfig, PollingPolicy

_MONGODB_URL = "mongodb://localhost:27017"
_MONGODB_DB_NAME = "canterlot_test"


def describe_database_manager():
    async def it_initializes_hoodie_on_open():
        mock_database = MagicMock()
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_database
        polling = HoodiePollingConfig(search_sync=PollingPolicy(max_attempts=1, initial_interval=0.01))

        with (
            patch("canterlot.hoodie.database.AsyncMongoClient", return_value=mock_client),
            patch("canterlot.hoodie.database.init_hoodie", new_callable=AsyncMock) as mock_init_hoodie,
        ):
            manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME, polling=polling)
            await manager.open()

            mock_init_hoodie.assert_awaited_once_with(mock_database, polling=polling)

    async def it_drops_and_reinitializes_on_reset():
        mock_database = MagicMock()
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_database

        with (
            patch("canterlot.hoodie.database.AsyncMongoClient", return_value=mock_client),
            patch("canterlot.hoodie.database.init_hoodie", new_callable=AsyncMock),
            patch("canterlot.hoodie.database.reset_hoodie", new_callable=AsyncMock) as mock_reset_hoodie,
        ):
            manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME)
            await manager.open()
            await manager.reset()

            mock_reset_hoodie.assert_awaited_once_with(mock_database)

    async def it_raises_when_resetting_before_open():
        manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME)

        with pytest.raises(DatabaseManagerNotOpenError):
            await manager.reset()

    async def it_closes_the_client_when_open():
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with (
            patch("canterlot.hoodie.database.AsyncMongoClient", return_value=mock_client),
            patch("canterlot.hoodie.database.init_hoodie", new_callable=AsyncMock),
        ):
            manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME)
            await manager.open()
            await manager.close()

            mock_client.close.assert_awaited_once()

    async def it_does_nothing_when_closing_before_open():
        manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME)

        await manager.close()

    async def it_raises_when_resetting_after_close():
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with (
            patch("canterlot.hoodie.database.AsyncMongoClient", return_value=mock_client),
            patch("canterlot.hoodie.database.init_hoodie", new_callable=AsyncMock),
        ):
            manager = DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME)
            await manager.open()
            await manager.close()

            with pytest.raises(DatabaseManagerNotOpenError):
                await manager.reset()

    async def it_supports_async_context_manager_lifecycle():
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with (
            patch("canterlot.hoodie.database.AsyncMongoClient", return_value=mock_client),
            patch("canterlot.hoodie.database.init_hoodie", new_callable=AsyncMock),
        ):
            async with DatabaseManager(_MONGODB_URL, _MONGODB_DB_NAME) as manager:
                assert isinstance(manager, DatabaseManager)

            mock_client.close.assert_awaited_once()
