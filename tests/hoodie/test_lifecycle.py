import pytest
from pymongo import AsyncMongoClient

from canterlot.hoodie import delete_all_entities, init_hoodie, reset_hoodie
from tests.hoodie.entities import PlainTestEntity, SearchableTestEntity, is_searchable
from tests.mongo_integration import DB_NAME

pytestmark = pytest.mark.asyncio(loop_scope="session")


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
