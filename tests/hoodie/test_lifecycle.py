import pytest
from pymongo import AsyncMongoClient, monitoring

from canterlot.hoodie import delete_all_entities, init_hoodie, reset_hoodie
from canterlot.hoodie.indexes import drop_registered_search_indexes
from tests.hoodie.entities import PlainTestEntity, SearchableTestEntity, is_searchable
from tests.mongo_integration import DB_NAME

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _CommandRecorder(monitoring.CommandListener):
    def __init__(self) -> None:
        self.command_names: list[str] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        self.command_names.append(event.command_name)

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


def describe_delete_all_entities() -> None:
    async def it_deletes_documents_across_every_registered_entity() -> None:
        await PlainTestEntity(label="a").insert()
        await SearchableTestEntity(label="b").insert()

        await delete_all_entities()

        assert await PlainTestEntity.find_all().count() == 0
        assert await SearchableTestEntity.find_all().count() == 0


def describe_init_hoodie() -> None:
    async def it_can_be_called_again_without_error(hoodie_client: AsyncMongoClient) -> None:
        await init_hoodie(hoodie_client[DB_NAME])

        entity = await PlainTestEntity(label="post-reinitialize").insert()
        assert await PlainTestEntity.get(entity.id) is not None


def describe_init_hoodie_with_search_disabled() -> None:
    async def it_skips_write_through_search_verification_entirely(hoodie_client: AsyncMongoClient) -> None:
        await init_hoodie(hoodie_client[DB_NAME], search=False)
        try:
            # Without this skip, it would poll against a never-built index and eventually
            # raise DocumentNeverSearchableError instead of returning promptly.
            entity = await SearchableTestEntity(label="search-disabled").insert()
            assert entity.id is not None
        finally:
            await init_hoodie(hoodie_client[DB_NAME], search=True)

    async def it_leaves_search_enabled_once_reenabled(hoodie_client: AsyncMongoClient) -> None:
        await init_hoodie(hoodie_client[DB_NAME], search=False)
        await init_hoodie(hoodie_client[DB_NAME], search=True)

        entity = await SearchableTestEntity(label="search-reenabled").insert()

        assert await is_searchable(entity)


def describe_reset_hoodie() -> None:
    async def it_drops_and_rebuilds_every_registered_entitys_collection(hoodie_client: AsyncMongoClient) -> None:
        stale = await PlainTestEntity(label="before-reset").insert()

        await reset_hoodie(hoodie_client[DB_NAME])

        assert await PlainTestEntity.get(stale.id) is None

        recreated = await PlainTestEntity(label="after-reset").insert()
        assert await PlainTestEntity.get(recreated.id) is not None

        searchable_entity = await SearchableTestEntity(label="post-reset-searchable").insert()
        assert await is_searchable(searchable_entity)

    async def it_drops_every_search_index_before_dropping_any_collection(
        hoodie_client: AsyncMongoClient,
        mongodb_container: tuple[str, int],
    ) -> None:
        host, port = mongodb_container
        recorder = _CommandRecorder()
        monitored_client: AsyncMongoClient = AsyncMongoClient(
            f"mongodb://{host}:{port}/?directConnection=true",
            tz_aware=True,
            event_listeners=[recorder],
        )

        try:
            await init_hoodie(monitored_client[DB_NAME])
            recorder.command_names.clear()

            await reset_hoodie(monitored_client[DB_NAME])

            index_drops = [i for i, name in enumerate(recorder.command_names) if name == "dropSearchIndex"]
            collection_drops = [i for i, name in enumerate(recorder.command_names) if name == "drop"]
            assert index_drops
            assert collection_drops
            assert max(index_drops) < min(collection_drops)
        finally:
            await init_hoodie(hoodie_client[DB_NAME])
            await monitored_client.close()


def describe_drop_registered_search_indexes() -> None:
    async def it_removes_every_registered_search_index(hoodie_client: AsyncMongoClient) -> None:
        collection = SearchableTestEntity.get_pymongo_collection()
        assert await (await collection.list_search_indexes()).to_list()

        try:
            await drop_registered_search_indexes()

            assert await (await collection.list_search_indexes()).to_list() == []
        finally:
            await init_hoodie(hoodie_client[DB_NAME])

    async def it_does_nothing_when_no_search_index_is_listed(hoodie_client: AsyncMongoClient) -> None:
        collection = SearchableTestEntity.get_pymongo_collection()

        try:
            await drop_registered_search_indexes()
            await drop_registered_search_indexes()

            assert await (await collection.list_search_indexes()).to_list() == []
        finally:
            await init_hoodie(hoodie_client[DB_NAME])
