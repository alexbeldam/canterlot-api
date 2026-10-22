# Beanie accepts a Document where the synthesized Link field type does not.
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from beanie import BulkWriter, DeleteRules, Document, PydanticObjectId, WriteRules, init_beanie
from beanie.odm.interfaces.session import SessionMethods
from beanie.odm.operators.update.general import Set
from beanie.odm.queries.aggregation import AggregationQuery
from beanie.odm.queries.delete import DeleteMany, DeleteOne
from beanie.odm.queries.find import FindMany, FindOne
from beanie.odm.queries.update import UpdateMany, UpdateOne, UpdateQuery
from pymongo import AsyncMongoClient, monitoring

from canterlot.hoodie import TransactionError, transactional
from tests.hoodie.conftest import CommandRecorder
from tests.hoodie.entities import (
    CustomMethodTestEntity,
    NoSessionMethodTestEntity,
    PlainTestEntity,
    RequiredSessionMethodTestEntity,
    SessionPathItem,
    SessionPathParent,
    SubCustomMethodTestEntity,
)
from tests.mongo_integration import DB_NAME

pytestmark = pytest.mark.asyncio(loop_scope="session")

ITEMS_COLLECTION = "hoodie_test_session_path_items"
PARENTS_COLLECTION = "hoodie_test_session_path_parents"


@dataclass
class Seeded:
    i1: SessionPathItem
    i2: SessionPathItem
    i3: SessionPathItem
    parent: SessionPathParent
    parent_with_unresolved_links: SessionPathParent


@dataclass(frozen=True)
class PathCase:
    id: str
    covers: tuple[str, ...]
    run: Callable[[Seeded], Awaitable[Any]]
    reads_only: bool = False


async def seed() -> Seeded:
    i1, i2, i3 = (SessionPathItem(name=f"synthetic-{k}", n=k) for k in (1, 2, 3))
    for item in (i1, i2, i3):
        await item.insert()

    parent = SessionPathParent(name="synthetic-parent", child=i1, kids=[i2])
    await parent.insert()
    reloaded = await SessionPathParent.get(parent.id)
    assert reloaded is not None
    return Seeded(i1, i2, i3, parent, reloaded)


async def _insert(_: Seeded) -> Any:
    return await SessionPathItem(name="synthetic-new").insert()


async def _save_existing(s: Seeded) -> Any:
    s.i1.n = 99
    return await s.i1.save()


async def _save_new(_: Seeded) -> Any:
    return await SessionPathItem(id=PydanticObjectId(), name="synthetic-new").save()


async def _replace(s: Seeded) -> Any:
    s.i1.n = 50
    return await s.i1.replace()


async def _update(s: Seeded) -> Any:
    return await s.i1.update(Set({SessionPathItem.n: 7}))


async def _set(s: Seeded) -> Any:
    return await s.i1.set({SessionPathItem.n: 7})


async def _inc(s: Seeded) -> Any:
    return await s.i1.inc({SessionPathItem.n: 1})


async def _current_date(s: Seeded) -> Any:
    return await s.i1.current_date({SessionPathItem.ts: True})  # type: ignore[dict-item]  # pyright: ignore[reportArgumentType]


async def _save_changes(s: Seeded) -> Any:
    s.i1.n = 33
    return await s.i1.save_changes()


async def _delete(s: Seeded) -> Any:
    return await s.i1.delete()


async def _insert_one(_: Seeded) -> Any:
    return await SessionPathItem.insert_one(SessionPathItem(name="synthetic-new"))


async def _insert_many(_: Seeded) -> Any:
    return await SessionPathItem.insert_many([SessionPathItem(name="synthetic-a"), SessionPathItem(name="synthetic-b")])


async def _replace_many(s: Seeded) -> Any:
    s.i1.n, s.i2.n = 11, 12
    return await SessionPathItem.replace_many([s.i1, s.i2])


async def _update_all(_: Seeded) -> Any:
    return await SessionPathItem.update_all(Set({SessionPathItem.n: 5}))


async def _delete_all(_: Seeded) -> Any:
    return await SessionPathItem.delete_all()


async def _find_update(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).update(Set({SessionPathItem.n: 5}))  # pyright: ignore[reportGeneralTypeIssues]


async def _find_update_many(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).update_many(Set({SessionPathItem.n: 5}))


async def _find_upsert(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.name == "synthetic-none").upsert(  # pyright: ignore[reportGeneralTypeIssues]
        Set({SessionPathItem.n: 5}),
        on_insert=SessionPathItem(name="synthetic-none"),
    )


async def _find_delete(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).delete()


async def _find_delete_many(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).delete_many()


async def _find_one_update(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.n == 1).update(Set({SessionPathItem.n: 5}))


async def _find_one_update_one(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.n == 1).update_one(Set({SessionPathItem.n: 5}))


async def _find_one_upsert(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.name == "synthetic-none").upsert(
        Set({SessionPathItem.n: 5}),
        on_insert=SessionPathItem(name="synthetic-none"),
    )


async def _find_one_delete(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.n == 1).delete()


async def _find_one_delete_one(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.n == 1).delete_one()


async def _find_one_replace_one(s: Seeded) -> Any:
    s.i1.n = 77
    return await SessionPathItem.find_one(SessionPathItem.n == 1).replace_one(s.i1)


async def _entity_bulk_writer_update(_: Seeded) -> Any:
    async with SessionPathItem.bulk_writer() as writer:
        await SessionPathItem.find_one(SessionPathItem.n == 1).update(Set({SessionPathItem.n: 5}), bulk_writer=writer)


async def _entity_bulk_writer_insert(_: Seeded) -> Any:
    async with SessionPathItem.bulk_writer() as writer:
        await SessionPathItem.insert_one(SessionPathItem(name="synthetic-new"), bulk_writer=writer)


async def stock_bulk_writer_insert(_: Seeded) -> Any:
    async with BulkWriter() as writer:
        await SessionPathItem.insert_one(SessionPathItem(name="synthetic-new"), bulk_writer=writer)


async def _link_insert(_: Seeded) -> Any:
    parent = SessionPathParent(
        name="synthetic-p",
        child=SessionPathItem(name="synthetic-c"),
        kids=[SessionPathItem(name="synthetic-k")],
    )
    return await parent.insert(link_rule=WriteRules.WRITE)


async def _link_save(s: Seeded) -> Any:
    s.parent.child = SessionPathItem(name="synthetic-c")
    return await s.parent.save(link_rule=WriteRules.WRITE)


async def _link_replace(s: Seeded) -> Any:
    s.i1.n = 41
    s.parent.child, s.parent.kids = s.i1, [s.i2]
    return await s.parent.replace(link_rule=WriteRules.WRITE)


async def _link_delete(s: Seeded) -> Any:
    s.parent.child, s.parent.kids = s.i1, [s.i2]
    return await s.parent.delete(link_rule=DeleteRules.DELETE_LINKS)


async def _get(s: Seeded) -> Any:
    return await SessionPathItem.get(s.i1.id)


async def _find_to_list(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).to_list()


async def _find_one(_: Seeded) -> Any:
    return await SessionPathItem.find_one(SessionPathItem.n == 1)


async def _find_first_or_none(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).first_or_none()


async def _find_count(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).count()


async def _find_exists(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).exists()


async def _find_distinct(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).distinct("n")


async def _document_distinct(_: Seeded) -> Any:
    return await SessionPathItem.distinct("n")


async def _document_count(_: Seeded) -> Any:
    return await SessionPathItem.count()


async def _find_aggregate(_: Seeded) -> Any:
    return await (
        SessionPathItem.find(SessionPathItem.n > 0)
        .aggregate([{"$group": {"_id": None, "t": {"$sum": "$n"}}}])
        .to_list()
    )


async def _document_aggregate(_: Seeded) -> Any:
    return await SessionPathItem.aggregate([{"$match": {}}]).to_list()


async def _sum(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).sum(SessionPathItem.n)


async def _avg(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).avg(SessionPathItem.n)


async def _max(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).max(SessionPathItem.n)


async def _min(_: Seeded) -> Any:
    return await SessionPathItem.find(SessionPathItem.n > 0).min(SessionPathItem.n)


async def _fetch_links(_: Seeded) -> Any:
    return await SessionPathParent.find(fetch_links=True).to_list()


async def _fetch_all_links(s: Seeded) -> Any:
    return await s.parent_with_unresolved_links.fetch_all_links()


async def _fetch_link(s: Seeded) -> Any:
    return await s.parent_with_unresolved_links.fetch_link(SessionPathParent.child)


async def _sync(s: Seeded) -> Any:
    return await s.i1.sync()


async def _inspect_collection(_: Seeded) -> Any:
    return await SessionPathItem.inspect_collection()


async def _find_all_iteration(_: Seeded) -> Any:
    return [doc async for doc in SessionPathItem.find_all()]


CASES: tuple[PathCase, ...] = (
    PathCase("insert", ("Document.insert",), _insert),
    PathCase("save existing", ("Document.save",), _save_existing),
    PathCase("save new id", ("Document.save",), _save_new),
    PathCase("replace", ("Document.replace", "FindOne.replace_one"), _replace),
    PathCase(
        "update instance",
        ("Document.update", "UpdateMethods.update", "FindOne.update", "UpdateOne.update", "UpdateOne.__await__"),
        _update,
    ),
    PathCase("set", ("Document.set", "UpdateMethods.set"), _set),
    PathCase("inc", ("Document.inc", "UpdateMethods.inc"), _inc),
    PathCase("current_date", ("Document.current_date", "UpdateMethods.current_date"), _current_date),
    PathCase("save_changes", ("Document.save_changes",), _save_changes),
    PathCase(
        "delete instance",
        ("Document.delete", "FindQuery.delete", "DeleteMany.__await__", "DeleteOne.__await__"),
        _delete,
    ),
    PathCase("insert_one", ("Document.insert_one", "Document.create"), _insert_one),
    PathCase("insert_many", ("Document.insert_many",), _insert_many),
    PathCase("replace_many", ("Document.replace_many",), _replace_many),
    PathCase("update_all", ("Document.update_all",), _update_all),
    PathCase("delete_all", ("Document.delete_all",), _delete_all),
    PathCase("find update", ("FindMany.update", "UpdateMany.update", "UpdateMany.__await__"), _find_update),
    PathCase("find update_many", ("FindMany.update_many", "UpdateMany.update_many"), _find_update_many),
    PathCase("find upsert", ("FindMany.upsert", "UpdateMany.upsert"), _find_upsert),
    PathCase("find delete", ("FindQuery.delete",), _find_delete),
    PathCase("find delete_many", ("FindMany.delete_many",), _find_delete_many),
    PathCase("find_one update", ("FindOne.update",), _find_one_update),
    PathCase("find_one update_one", ("FindOne.update_one", "UpdateOne.update_one"), _find_one_update_one),
    PathCase("find_one upsert", ("FindOne.upsert", "UpdateOne.upsert"), _find_one_upsert),
    PathCase("find_one delete", ("FindQuery.delete",), _find_one_delete),
    PathCase("find_one delete_one", ("FindOne.delete_one",), _find_one_delete_one),
    PathCase("find_one replace_one", ("FindOne.replace_one",), _find_one_replace_one),
    PathCase(
        "Entity.bulk_writer update",
        ("Document.bulk_writer", "BulkWriter.__aenter__", "BulkWriter.__aexit__", "BulkWriter.commit"),
        _entity_bulk_writer_update,
    ),
    PathCase("Entity.bulk_writer insert_one", (), _entity_bulk_writer_insert),
    PathCase("link WRITE insert", (), _link_insert),
    PathCase("link WRITE save", (), _link_save),
    PathCase("link WRITE replace", (), _link_replace),
    PathCase("link DELETE_LINKS delete", (), _link_delete),
    PathCase(
        "get",
        ("Document.get", "FindInterface.find_one", "FindOne.find_one", "FindOne.__await__"),
        _get,
        reads_only=True,
    ),
    PathCase(
        "find to_list",
        (
            "BaseCursorQuery.to_list",
            "BaseCursorQuery.get_cursor",
            "FindMany.get_cursor",
            "FindInterface.find",
            "FindInterface.find_many",
            "FindMany.find",
            "FindMany.find_many",
            "FindInterface.all",
            "FindInterface.find_all",
        ),
        _find_to_list,
        reads_only=True,
    ),
    PathCase("find_one", ("FindOne.__await__",), _find_one, reads_only=True),
    PathCase("find first_or_none", ("FindMany.first_or_none",), _find_first_or_none, reads_only=True),
    PathCase("find count", ("FindMany.count", "FindQuery.count", "FindOne.count"), _find_count, reads_only=True),
    PathCase("find exists", ("FindQuery.exists",), _find_exists, reads_only=True),
    PathCase("find distinct", ("FindMany.distinct",), _find_distinct, reads_only=True),
    PathCase("Document.distinct", ("Document.distinct",), _document_distinct, reads_only=True),
    PathCase("Document.count", ("FindInterface.count",), _document_count, reads_only=True),
    PathCase(
        "find aggregate",
        ("FindMany.aggregate", "AggregationQuery.get_cursor", "AggregateMethods.aggregate"),
        _find_aggregate,
        reads_only=True,
    ),
    PathCase("Document.aggregate", ("AggregateInterface.aggregate",), _document_aggregate, reads_only=True),
    PathCase("sum", ("AggregateMethods.sum", "AggregateInterface.sum"), _sum, reads_only=True),
    PathCase("avg", ("AggregateMethods.avg", "AggregateInterface.avg"), _avg, reads_only=True),
    PathCase("max", ("AggregateMethods.max", "AggregateInterface.max"), _max, reads_only=True),
    PathCase("min", ("AggregateMethods.min", "AggregateInterface.min"), _min, reads_only=True),
    PathCase("find fetch_links", (), _fetch_links, reads_only=True),
    PathCase("fetch_all_links", ("Document.fetch_all_links",), _fetch_all_links, reads_only=True),
    PathCase("fetch_link", ("Document.fetch_link",), _fetch_link, reads_only=True),
    PathCase("sync", ("Document.sync",), _sync, reads_only=True),
    PathCase("inspect_collection", ("Document.inspect_collection",), _inspect_collection, reads_only=True),
    PathCase("find_all iteration", ("BaseCursorQuery.__anext__",), _find_all_iteration, reads_only=True),
)

# Discovered Beanie methods that are deliberately not exercised, each with the reason.
EXEMPT: dict[str, str] = {
    "Document.validate_self": "pure validation, no driver call",
    "SessionMethods.set_session": "builder plumbing, not a driver call",
}

_ROOTS: tuple[type, ...] = (
    Document,
    FindMany,
    FindOne,
    UpdateQuery,
    UpdateMany,
    UpdateOne,
    DeleteMany,
    DeleteOne,
    AggregationQuery,
    BulkWriter,
)
_ALWAYS_DISCOVERED = frozenset({"__aenter__", "__aexit__", "__await__", "__anext__"})


def _unwrapped(raw: Any) -> Any:
    return inspect.unwrap(raw.__func__ if isinstance(raw, classmethod | staticmethod) else raw)


def _may_reach_the_driver(fn: Any) -> bool:
    if not callable(fn):
        return False
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "session" in parameters or "bulk_writer" in parameters or inspect.iscoroutinefunction(fn)


def discover_beanie_driver_methods() -> set[str]:
    found: set[str] = set()
    for root in _ROOTS:
        for cls in root.__mro__:
            if cls.__module__.split(".")[0] != "beanie":
                continue
            for name, raw in vars(cls).items():
                if name.startswith("_") and name not in _ALWAYS_DISCOVERED:
                    continue
                if isinstance(raw, property | type):
                    continue
                if name in _ALWAYS_DISCOVERED or _may_reach_the_driver(_unwrapped(raw)):
                    found.add(f"{cls.__name__}.{name}")
    return found


DATA_COMMANDS = frozenset(
    {"insert", "update", "delete", "find", "aggregate", "count", "distinct", "bulkWrite", "findAndModify", "getMore"}
)


class Rollback(Exception):
    pass


def data_commands(events: list[monitoring.CommandStartedEvent]) -> list[monitoring.CommandStartedEvent]:
    return [e for e in events if e.database_name == DB_NAME and e.command_name in DATA_COMMANDS]


def is_in_transaction(event: monitoring.CommandStartedEvent) -> bool:
    return "lsid" in event.command and "txnNumber" in event.command and event.command.get("autocommit") is False


async def snapshot(client: AsyncMongoClient) -> dict[str, list[dict[str, Any]]]:
    return {
        name: sorted([doc async for doc in client[DB_NAME][name].find({})], key=lambda doc: str(doc["_id"]))
        for name in (ITEMS_COLLECTION, PARENTS_COLLECTION)
    }


async def stock_bulk_writer_update_all(_: Seeded) -> Any:
    async with BulkWriter() as writer:
        await SessionPathItem.update_all(Set({SessionPathItem.n: 5}), bulk_writer=writer)


class _PlainBeanieDocument(Document):
    label: str = "default"

    class Settings:
        name = "hoodie_test_plain_beanie_documents"


class _Boom(TransactionError):
    pass


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def plain_beanie_document(hoodie_client: AsyncMongoClient) -> AsyncIterator[type[_PlainBeanieDocument]]:
    await init_beanie(database=hoodie_client[DB_NAME], document_models=[_PlainBeanieDocument])
    yield _PlainBeanieDocument
    await _PlainBeanieDocument.delete_all()


def describe_session_injection() -> None:
    async def it_applies_the_ambient_transaction_session_to_a_query_builder_write_with_no_explicit_session() -> None:
        entity = await PlainTestEntity(label="before").insert()

        @transactional
        async def update_then_fail() -> None:
            await PlainTestEntity.find_one(PlainTestEntity.id == entity.id).update_one({"$set": {"label": "after"}})
            raise _Boom

        with pytest.raises(_Boom):
            await update_then_fail()

        # If the update hadn't picked up the ambient session, it would survive _Boom's rollback.
        refreshed = await PlainTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.label == "before"

    async def it_applies_the_ambient_transaction_session_to_insert_with_no_explicit_session() -> None:
        # insert() calls pymongo directly, exercising _enable_session_injection, not the
        # SessionMethods.set_session patch.
        @transactional
        async def insert_then_fail() -> PlainTestEntity:
            await PlainTestEntity(label="inserted").insert()
            raise _Boom

        with pytest.raises(_Boom):
            await insert_then_fail()

        assert await PlainTestEntity.find(PlainTestEntity.label == "inserted").count() == 0

    async def it_applies_the_ambient_transaction_session_to_save_with_no_explicit_session() -> None:
        entity = await PlainTestEntity(label="before").insert()

        @transactional
        async def save_then_fail() -> None:
            entity.label = "after"
            await entity.save()
            raise _Boom

        with pytest.raises(_Boom):
            await save_then_fail()

        refreshed = await PlainTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.label == "before"

    async def it_applies_the_ambient_transaction_session_to_replace_with_no_explicit_session() -> None:
        entity = await PlainTestEntity(label="before").insert()

        @transactional
        async def replace_then_fail() -> None:
            entity.label = "after"
            await entity.replace()
            raise _Boom

        with pytest.raises(_Boom):
            await replace_then_fail()

        refreshed = await PlainTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.label == "before"

    async def it_applies_the_ambient_transaction_session_to_instance_delete_with_no_explicit_session() -> None:
        entity = await PlainTestEntity(label="doomed").insert()

        @transactional
        async def delete_then_fail() -> None:
            await entity.delete()
            raise _Boom

        with pytest.raises(_Boom):
            await delete_then_fail()

        assert await PlainTestEntity.get(entity.id) is not None

    async def it_applies_the_ambient_transaction_session_to_a_custom_direct_pymongo_method() -> None:
        # bump_directly() bypasses beanie's query builders entirely, same as insert/insert_many,
        # proving _enable_session_injection's generic scan (not the hardcoded names) covers it.
        entity = await CustomMethodTestEntity(counter=0).insert()

        @transactional
        async def bump_then_fail() -> None:
            await entity.bump_directly()
            raise _Boom

        with pytest.raises(_Boom):
            await bump_then_fail()

        refreshed = await CustomMethodTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.counter == 0

    async def it_leaves_a_custom_method_with_no_session_parameter_unwrapped() -> None:
        entity = await NoSessionMethodTestEntity(counter=21).insert()

        assert await entity.double_counter() == 42

    async def it_applies_the_ambient_transaction_session_to_a_custom_method_with_a_bare_session_annotation() -> None:
        # bump_directly here annotates session as AsyncClientSession, not Optional[...],
        # exercising _is_async_client_session_type's direct-match branch.
        entity = await RequiredSessionMethodTestEntity(counter=0).insert()

        @transactional
        async def bump_then_fail() -> None:
            await entity.bump_directly()  # type: ignore[call-arg]
            raise _Boom

        with pytest.raises(_Boom):
            await bump_then_fail()

        refreshed = await RequiredSessionMethodTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.counter == 0

    async def it_leaves_a_non_entity_document_without_the_ambient_session(
        plain_beanie_document: type[_PlainBeanieDocument],
        command_recorder: CommandRecorder,
    ) -> None:
        document = await plain_beanie_document(label="before").insert()

        @transactional
        async def touch_then_roll_back() -> None:
            await plain_beanie_document.find_one(plain_beanie_document.id == document.id).update_one(
                {"$set": {"label": "after"}},
            )
            await plain_beanie_document.find(plain_beanie_document.id == document.id).to_list()
            raise Rollback

        with command_recorder.recording() as events, pytest.raises(Rollback):
            await touch_then_roll_back()

        touched = [e for e in data_commands(events) if "hoodie_test_plain_beanie_documents" in str(e.command)]
        assert touched
        assert not any(is_in_transaction(e) for e in touched)
        refreshed = await plain_beanie_document.get(document.id)
        assert refreshed is not None
        assert refreshed.label == "after"

    async def it_never_patches_beanies_session_methods() -> None:
        assert SessionMethods.set_session.__module__.startswith("beanie")

    async def it_prefers_an_explicitly_set_session_over_the_ambient_one(
        hoodie_client: AsyncMongoClient,
        command_recorder: CommandRecorder,
    ) -> None:
        item = await SessionPathItem(name="synthetic-explicit").insert()

        async with hoodie_client.start_session() as explicit_session:

            @transactional
            async def update_with_explicit_session() -> None:
                await SessionPathItem.find_one(SessionPathItem.id == item.id).update_one(
                    {"$set": {"n": 5}},
                    session=explicit_session,
                )

            with command_recorder.recording() as events:
                await update_with_explicit_session()

            updates = [e for e in data_commands(events) if e.command_name == "update"]
            assert updates
            assert {e.command["lsid"]["id"] for e in updates} == {explicit_session.session_id["id"]}

    async def it_keeps_using_the_ambient_session_when_none_is_passed_explicitly(
        command_recorder: CommandRecorder,
    ) -> None:
        item = await SessionPathItem(name="synthetic-no-opt-out").insert()

        @transactional
        async def write_with_session_none() -> None:
            await SessionPathItem.find_one(SessionPathItem.id == item.id).update_one({"$set": {"n": 5}}, session=None)
            await SessionPathItem(name="synthetic-inserted").insert(session=None)
            raise Rollback

        with command_recorder.recording() as events, pytest.raises(Rollback):
            await write_with_session_none()

        commands = data_commands(events)
        assert commands
        assert all(is_in_transaction(e) for e in commands)
        assert await SessionPathItem.find(SessionPathItem.name == "synthetic-inserted").count() == 0

    async def it_runs_a_builder_awaited_after_its_transaction_ended_outside_that_transaction(
        command_recorder: CommandRecorder,
    ) -> None:
        item = await SessionPathItem(name="synthetic-late", n=1).insert()

        @transactional
        async def build_without_awaiting() -> object:
            return SessionPathItem.find_one(SessionPathItem.id == item.id).update_one({"$set": {"n": 2}})

        builder = await build_without_awaiting()
        with command_recorder.recording() as events:
            await builder  # type: ignore[misc]

        commands = data_commands(events)
        assert commands
        assert not any(is_in_transaction(e) for e in commands)
        refreshed = await SessionPathItem.get(item.id)
        assert refreshed is not None
        assert refreshed.n == 2

    async def it_isolates_two_concurrent_transactions_from_each_other(
        command_recorder: CommandRecorder,
    ) -> None:
        barrier = asyncio.Barrier(2)

        @transactional
        async def write_through_own_transaction(tag: str) -> None:
            await SessionPathItem(name=tag).insert()
            await barrier.wait()
            await SessionPathItem.find_one(SessionPathItem.name == tag).update_one({"$set": {"n": 9}})
            await barrier.wait()

        with command_recorder.recording() as events:
            await asyncio.gather(
                write_through_own_transaction("synthetic-a"), write_through_own_transaction("synthetic-b")
            )

        lsids_by_tag: dict[str, set[object]] = {}
        for tag in ("synthetic-a", "synthetic-b"):
            tagged = [e for e in data_commands(events) if tag in str(e.command)]
            assert len(tagged) >= 2
            assert all(is_in_transaction(e) for e in tagged)
            lsids_by_tag[tag] = {e.command["lsid"]["id"] for e in tagged}

        assert all(len(lsids) == 1 for lsids in lsids_by_tag.values())
        assert lsids_by_tag["synthetic-a"] != lsids_by_tag["synthetic-b"]
        assert await SessionPathItem.find(SessionPathItem.n == 9).count() == 2

    @pytest.mark.parametrize("write", [stock_bulk_writer_insert, stock_bulk_writer_update_all])
    async def it_lets_a_stock_bulk_writer_escape_the_transaction(
        write: Callable[[Seeded], Awaitable[Any]],
        hoodie_client: AsyncMongoClient,
        command_recorder: CommandRecorder,
    ) -> None:
        seeded = await seed()
        before = await snapshot(hoodie_client)

        @transactional
        async def bulk_write_then_roll_back() -> None:
            await write(seeded)
            raise Rollback

        with command_recorder.recording() as events, pytest.raises(Rollback):
            await bulk_write_then_roll_back()

        bulk_writes = [e for e in data_commands(events) if e.command_name in {"bulkWrite", "insert", "update"}]
        assert bulk_writes
        assert not any(is_in_transaction(e) for e in bulk_writes)
        assert await snapshot(hoodie_client) != before

    async def it_applies_the_ambient_transaction_session_to_a_custom_method_inherited_by_a_subclass() -> None:
        # bump_directly is wrapped once, on the parent's own __dict__, and inherited from there.
        entity = await SubCustomMethodTestEntity(counter=0).insert()

        @transactional
        async def bump_then_fail() -> None:
            await entity.bump_directly()
            raise _Boom

        with pytest.raises(_Boom):
            await bump_then_fail()

        refreshed = await SubCustomMethodTestEntity.get(entity.id)
        assert refreshed is not None
        assert refreshed.counter == 0


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def it_sends_every_command_of_the_path_inside_the_ambient_transaction(
    case: PathCase,
    hoodie_client: AsyncMongoClient,
    command_recorder: CommandRecorder,
) -> None:
    seeded = await seed()
    before = await snapshot(hoodie_client)

    @transactional
    async def run_then_rollback() -> None:
        await case.run(seeded)
        raise Rollback

    with command_recorder.recording() as events, pytest.raises(Rollback):
        await run_then_rollback()

    commands = data_commands(events)
    assert commands, "the path sent no data command"
    outside = sorted({e.command_name for e in commands if not is_in_transaction(e)})
    assert not outside, f"commands sent outside the transaction: {outside}"
    assert len({e.command["lsid"]["id"] for e in commands}) == 1
    if not case.reads_only:
        assert await snapshot(hoodie_client) == before, "a write survived the rollback"


# Present only on some supported Beanie versions.
VERSION_DEPENDENT = frozenset({"FindMany.distinct"})


def covered_methods() -> set[str]:
    return {name for case in CASES for name in case.covers}


def describe_beanie_driver_methods() -> None:
    async def it_has_a_path_test_or_an_exemption_for_every_method_that_can_reach_the_driver() -> None:
        unknown = sorted(discover_beanie_driver_methods() - covered_methods() - EXEMPT.keys())

        assert not unknown, f"Beanie methods with neither a session path case nor an exemption: {unknown}"

    async def it_names_no_covered_or_exempt_method_that_beanie_no_longer_has() -> None:
        stale = sorted((covered_methods() | EXEMPT.keys()) - discover_beanie_driver_methods() - VERSION_DEPENDENT)

        assert not stale, f"cases or exemptions naming methods Beanie no longer has: {stale}"
