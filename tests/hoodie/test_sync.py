import asyncio

import pytest
from beanie import BulkWriter, PydanticObjectId
from beanie.operators import In
from pymongo import AsyncMongoClient

from canterlot.hoodie import (
    HoodiePollingConfig,
    SyncKind,
    get_polling_config,
    set_polling_config,
    sync_search,
    synced,
)
from canterlot.hoodie.exceptions import (
    DocumentNeverSearchableError,
    DocumentNeverUnsearchableError,
    InvalidSessionTypeError,
    SyncedOwnerTypeError,
    UnknownSearchIndexError,
    UnmanagedSessionError,
)
from canterlot.hoodie.polling import PollingPolicy
from tests.hoodie.conftest import CommandRecorder
from tests.hoodie.entities import PlainTestEntity, SearchableTestEntity, is_searchable

pytestmark = pytest.mark.asyncio(loop_scope="session")

_SEARCH_INDEX = "hoodie_test_searchable_entities_search"


def describe_write_hooks() -> None:
    async def it_leaves_a_fresh_insert_immediately_searchable() -> None:
        entity = await SearchableTestEntity(label="freshly-inserted").insert()

        assert await is_searchable(entity)

    async def it_leaves_a_document_saved_via_a_nested_update_call_searchable() -> None:
        entity = SearchableTestEntity(label="saved-directly")
        await entity.save()

        assert await is_searchable(entity)

    async def it_does_not_require_a_search_index_for_a_plain_entity() -> None:
        entity = await PlainTestEntity(label="plain-write").insert()

        found = await PlainTestEntity.get(entity.id)
        assert found is not None

    async def it_still_completes_a_bulk_writer_replace() -> None:
        entity = await SearchableTestEntity(label="bulk-original").insert()

        async with BulkWriter() as writer:
            entity.label = "bulk-replaced"
            await entity.replace(bulk_writer=writer)

        updated = await SearchableTestEntity.get(entity.id)
        assert updated is not None
        assert updated.label == "bulk-replaced"

    async def it_raises_when_a_session_write_has_no_active_batch(hoodie_client: AsyncMongoClient) -> None:
        async with hoodie_client.start_session() as session:
            with pytest.raises(UnmanagedSessionError):
                await SearchableTestEntity(label="unmanaged-write").insert(session=session)

    async def it_leaves_a_batch_inserted_via_insert_many_searchable() -> None:
        entities = [SearchableTestEntity(label="batch-a"), SearchableTestEntity(label="batch-b")]

        result = await SearchableTestEntity.insert_many(entities)

        inserted = await SearchableTestEntity.find(In(SearchableTestEntity.id, result.inserted_ids)).to_list()
        assert len(inserted) == 2
        for entity in inserted:
            assert await is_searchable(entity)


def describe_write_verification_coalescing() -> None:
    async def it_shares_one_probe_between_concurrent_verifications_of_different_documents(
        command_recorder: CommandRecorder,
    ) -> None:
        first = await SearchableTestEntity(label="coalesce-a").insert()
        second = await SearchableTestEntity(label="coalesce-b").insert()

        with command_recorder.recording() as events:
            await asyncio.gather(
                sync_search(_SEARCH_INDEX, [PydanticObjectId(first.id)], SyncKind.WRITE, session=None),
                sync_search(_SEARCH_INDEX, [PydanticObjectId(second.id)], SyncKind.WRITE, session=None),
            )

        search_commands = [
            event
            for event in events
            if event.command_name == "aggregate" and "$search" in event.command.get("pipeline", [{}])[0]
        ]
        assert len(search_commands) == 1


def describe_a_cancelled_verification() -> None:
    async def it_does_not_fail_another_verification_sharing_its_wait_group() -> None:
        cancelled_doc = await SearchableTestEntity(label="cancelled-waiter").insert()
        surviving_doc = await SearchableTestEntity(label="surviving-waiter").insert()

        cancelled = asyncio.create_task(
            sync_search(_SEARCH_INDEX, [PydanticObjectId(cancelled_doc.id)], SyncKind.WRITE, session=None)
        )
        surviving = asyncio.create_task(
            sync_search(_SEARCH_INDEX, [PydanticObjectId(surviving_doc.id)], SyncKind.WRITE, session=None)
        )
        await asyncio.sleep(0)
        cancelled.cancel()

        await surviving
        with pytest.raises(asyncio.CancelledError):
            await cancelled


def describe_synced_with_an_explicit_entity() -> None:
    async def it_search_syncs_a_free_function_whose_first_argument_is_not_entity_shaped() -> None:
        @synced(entity=SearchableTestEntity)
        async def create_labeled(label: str) -> SearchableTestEntity:
            return await SearchableTestEntity(label=label).insert()

        entity = await create_labeled("free function sync")

        assert await is_searchable(entity)

    async def it_skips_search_verification_when_the_result_is_neither_an_entity_nor_an_insert_many_result() -> None:
        # Off-contract: exercises _build_pending_syncs' fallback for a result that's neither.
        @synced(entity=SearchableTestEntity)  # type: ignore[arg-type]
        async def create_and_return_nothing(label: str) -> None:
            await SearchableTestEntity(label=label).insert()

        result = await create_and_return_nothing("returns-none")

        assert result is None


def describe_synced_with_the_bare_decorator() -> None:
    async def it_raises_when_the_first_argument_isnt_entity_shaped() -> None:
        # Off-contract: bare @synced expects an Entity-shaped first argument.
        @synced  # type: ignore[type-var]
        async def not_entity_shaped(value: int) -> int:
            return value

        with pytest.raises(SyncedOwnerTypeError):
            await not_entity_shaped(5)


def describe_synced_with_an_invalid_session_value() -> None:
    async def it_raises_before_attempting_the_write() -> None:
        with pytest.raises(InvalidSessionTypeError):
            await SearchableTestEntity(label="bad-session").insert(session="not-a-session")  # type: ignore[arg-type]

        assert await SearchableTestEntity.find(SearchableTestEntity.label == "bad-session").count() == 0


def describe_sync_search_with_an_unregistered_index() -> None:
    async def it_raises_an_exception_group_wrapping_unknown_search_index_error() -> None:
        with pytest.raises(ExceptionGroup) as exc_info:
            await sync_search("no-such-registered-index", [PydanticObjectId()], SyncKind.WRITE, session=None)

        assert isinstance(exc_info.value.exceptions[0], UnknownSearchIndexError)


def describe_sync_search_when_a_document_never_settles() -> None:
    async def it_raises_document_never_searchable_error_for_a_write_that_never_settles() -> None:
        original_polling = get_polling_config()
        set_polling_config(HoodiePollingConfig(search_sync=PollingPolicy(max_attempts=2, initial_interval=0.01)))
        try:
            with pytest.raises(ExceptionGroup) as exc_info:
                await sync_search(_SEARCH_INDEX, [PydanticObjectId()], SyncKind.WRITE, session=None)
        finally:
            set_polling_config(original_polling)

        assert isinstance(exc_info.value.exceptions[0], DocumentNeverSearchableError)

    async def it_raises_document_never_unsearchable_error_for_a_delete_that_never_settles() -> None:
        # Configured after the setup insert: its own write-hook verification also polls the
        # active search_sync policy, and the real index needs more than two 0.01s attempts.
        entity = await SearchableTestEntity(label="still-searchable").insert()

        original_polling = get_polling_config()
        set_polling_config(HoodiePollingConfig(search_sync=PollingPolicy(max_attempts=2, initial_interval=0.01)))
        try:
            with pytest.raises(ExceptionGroup) as exc_info:
                await sync_search(_SEARCH_INDEX, [PydanticObjectId(entity.id)], SyncKind.DELETE, session=None)
        finally:
            set_polling_config(original_polling)

        assert isinstance(exc_info.value.exceptions[0], DocumentNeverUnsearchableError)
