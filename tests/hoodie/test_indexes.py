import asyncio
from unittest import mock

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from canterlot.hoodie import Entity, init_hoodie
from canterlot.hoodie.fields import searchable
from canterlot.hoodie.polling import poll_until
from tests.hoodie.conftest import CommandRecorder
from tests.hoodie.entities import Profile, SearchableTestEntity, is_searchable
from tests.mongo_integration import DB_NAME, SETTLE_POLICY

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _DriftableTestEntity(Entity):
    label: str = searchable(default="default")

    class Settings:
        name = "hoodie_test_driftable_entities"
        search_index = "hoodie_test_driftable_entities_search"


class _CoalescedIndexTestEntity(Entity):
    # Its own dedicated index, isolated from _DriftableTestEntity's, so the coalescing test
    # below isn't coupled to that other describe block's drift/restore state or ordering.
    label: str = searchable(default="default")

    class Settings:
        name = "hoodie_test_coalesced_index_entities"
        search_index = "hoodie_test_coalesced_index_entities_search"


async def _wait_until_label_analyzer_is(collection: AsyncCollection, index_name: str, analyzer: str) -> None:
    async def settled() -> bool:
        docs = await (await collection.list_search_indexes(index_name)).to_list()
        latest = docs[0].get("latestDefinition") if docs else None
        return bool(latest and latest["mappings"]["fields"]["label"]["analyzer"] == analyzer)

    if not await poll_until(settled, policy=SETTLE_POLICY, on_retry=lambda _attempt: None):
        raise AssertionError(f"{index_name} never echoed back analyzer={analyzer!r}.")


def describe_searchable_fields() -> None:
    async def it_builds_a_queryable_atlas_search_index_for_a_top_level_field() -> None:
        entity = await SearchableTestEntity(label="hello world").insert()

        assert await is_searchable(entity)

    async def it_builds_a_queryable_atlas_search_index_for_a_field_nested_under_a_submodel() -> None:
        entity = await SearchableTestEntity(profile=Profile(bio="hello world")).insert()

        assert await is_searchable(entity)


def describe_ensure_registered_search_indexes_when_nothing_changed() -> None:
    async def it_does_not_reupdate_an_unchanged_search_index(hoodie_client: AsyncMongoClient) -> None:
        with mock.patch.object(AsyncCollection, "update_search_index") as spy:
            await init_hoodie(hoodie_client[DB_NAME])

        spy.assert_not_called()


def describe_index_build_coalescing() -> None:
    async def it_shares_one_check_cycle_between_concurrent_calls_for_the_same_index(
        hoodie_client: AsyncMongoClient,
        command_recorder: CommandRecorder,
    ) -> None:
        index_name = "hoodie_test_coalesced_index_entities_search"

        with command_recorder.recording() as events:
            await asyncio.gather(
                init_hoodie(hoodie_client[DB_NAME]),
                init_hoodie(hoodie_client[DB_NAME]),
            )

        list_calls = [
            event
            for event in events
            if event.command_name == "aggregate"
            and event.command.get("pipeline", [{}])[0].get("$listSearchIndexes", {}).get("name") == index_name
        ]
        # One shared execution: the existence check plus the queryable-poll's own check,
        # not two of each from a second, uncoalesced execution racing the first.
        assert len(list_calls) == 2


def describe_ensure_registered_search_indexes_when_the_remote_definition_changed() -> None:
    async def it_reupdates_a_search_index_that_actually_drifted(hoodie_client: AsyncMongoClient) -> None:
        await init_hoodie(hoodie_client[DB_NAME])

        collection = _DriftableTestEntity.get_pymongo_collection()
        index_name = "hoodie_test_driftable_entities_search"
        drifted_definition = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "_id": {"type": "objectId"},
                    "label": {"type": "string", "analyzer": "lucene.keyword"},
                },
            }
        }
        await collection.update_search_index(index_name, drifted_definition)
        await _wait_until_label_analyzer_is(collection, index_name, "lucene.keyword")

        with mock.patch.object(AsyncCollection, "update_search_index") as spy:
            await init_hoodie(hoodie_client[DB_NAME])

        spy.assert_called()

        # Restore for real so later tests don't see this entity's index left drifted.
        await init_hoodie(hoodie_client[DB_NAME])
