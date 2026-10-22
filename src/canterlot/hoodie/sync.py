import asyncio
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, Protocol, overload

import structlog
from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.results import InsertManyResult

from .exceptions import (
    DocumentNeverSearchableError,
    DocumentNeverUnsearchableError,
    InvalidSessionTypeError,
    SyncedOwnerTypeError,
    UnknownSearchIndexError,
    UnmanagedSessionError,
)
from .polling import poll_until
from .query import SearchQuery
from .registry import _CURRENT_SESSION, _ENTITY_SEARCH_META, _INDEX_TO_ENTITY, get_polling_config, is_search_enabled

if TYPE_CHECKING:
    from .entity import Entity

logger = structlog.get_logger(__name__)

_batch: ContextVar["list[PendingSearchSync] | None"] = ContextVar("_batch", default=None)
_deferring: ContextVar[bool] = ContextVar("_deferring", default=False)


class SyncKind(StrEnum):
    """Which settlement state `sync_search`/`@synced` polls for: `WRITE` waits until a
    document appears (or is updated) in the search index; `DELETE` waits until it
    disappears."""

    WRITE = "WRITE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class PendingSearchSync:
    index_name: str
    doc_id: PydanticObjectId
    kind: SyncKind
    expected_fields: dict[str, Any] | None = None


class _EntitySyncedDecorator[E: "Entity"](Protocol):
    @overload
    def __call__[**P](self, fn: Callable[P, Awaitable[E]]) -> Callable[P, Coroutine[Any, Any, E]]: ...
    @overload
    def __call__[**P](
        self,
        fn: Callable[P, Awaitable[InsertManyResult]],
    ) -> Callable[P, Coroutine[Any, Any, InsertManyResult]]: ...


@overload
def synced[E: "Entity", **P](
    func: Callable[Concatenate[E, P], Awaitable[E]],
    /,
) -> Callable[Concatenate[E, P], Coroutine[Any, Any, E]]: ...


@overload
def synced[E: "Entity", **P](
    func: Callable[Concatenate[type[E], P], Awaitable[InsertManyResult]],
    /,
) -> Callable[Concatenate[type[E], P], Coroutine[Any, Any, InsertManyResult]]: ...


@overload
def synced[E: "Entity"](
    *,
    entity: type[E],
) -> _EntitySyncedDecorator[E]: ...


def synced(
    func: Callable[Concatenate[Any, ...], Awaitable[Any]] | None = None,
    /,
    *,
    entity: "type[Entity] | None" = None,
) -> Any:
    """Wraps a write method (or, with `entity=`, a free function) so a successful call is
    search-sync verified before returning.

    Bare `@synced` reads the target entity/entity type off the call's own first positional
    argument (self/cls), exactly like a method. `@synced(entity=SomeEntity)` is for a free
    function whose first parameter isn't Entity-shaped at all: the entity to sync against is
    given explicitly instead of read from the call. Either way, the entity is never inferred
    from the return value; a free function's `entity=` must be supplied by the caller.

    A call made with a `bulk_writer` deliberately skips this: bulk writes prioritize ingestion
    throughput, and the caller takes on responsibility for the index's eventual consistency.
    Silently a no-op (the wrapped call still runs, just without verification) when the target
    entity has no `Settings.search_index` configured, or when `init_hoodie` was last called
    with `search=False`, since there's no index to verify against in either case.

    :param func: the write method/function to wrap, used only when applying the decorator
        bare (`@synced`, no parentheses).
    :type func: Callable[..., Awaitable[Any]] | None
    :param entity: the Entity subclass to sync against, for a free function whose first
        argument isn't Entity-shaped.
    :type entity: type[Entity] | None
    :returns: the decorated method/function.
    :rtype: Any
    :raises SyncedOwnerTypeError: if the call's first argument (bare `@synced`) isn't an
        Entity instance or subclass.
    :raises InvalidSessionTypeError: if a non-None `session` argument isn't an
        `AsyncClientSession`, checked before the wrapped call runs - only when the target
        entity has a configured, enabled search index and no `bulk_writer`/nested-deferral
        skip applies; otherwise the call proceeds unchecked.
    :raises ExceptionGroup: wrapping a `DocumentNeverSearchableError`/
        `DocumentNeverUnsearchableError` per document that never settled.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
        sig = inspect.signature(fn)

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from .entity import Entity

            if entity is not None:
                owner_type = entity
            else:
                owner = args[0] if args else None
                if isinstance(owner, Entity):
                    owner_type = type(owner)
                elif isinstance(owner, type) and issubclass(owner, Entity):
                    owner_type = owner
                else:
                    raise SyncedOwnerTypeError(owner)

            # Skipped when the entity has no search index configured, or search is disabled
            # (no real index to verify against).
            meta = _ENTITY_SEARCH_META.get(owner_type)
            if meta is None or not is_search_enabled():
                return await fn(*args, **kwargs)

            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            bound = bound_args.arguments

            if bound.get("bulk_writer") is not None or _deferring.get():
                return await fn(*args, **kwargs)

            # Only insert/insert_many get the ambient session injected as an argument; the other
            # writes join the transaction through the query builder, so it is read from here.
            session = bound.get("session")
            if session is None:
                session = _CURRENT_SESSION.get()
            if session is not None and not isinstance(session, AsyncClientSession):
                raise InvalidSessionTypeError(session)

            token = _deferring.set(True)
            try:
                result = await fn(*args, **kwargs)
            finally:
                _deferring.reset(token)

            sync_entries = _build_pending_syncs(owner_type, result, meta.index)

            await sync_search_entries(sync_entries, session=session)
            return result

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def _build_pending_syncs(
    owner_type: "type[Entity]",
    result: Any,
    index_name: str,
) -> list[PendingSearchSync]:
    """Extracts expected field values from a write's result for post-write search validation."""
    from .entity import Entity

    meta = _ENTITY_SEARCH_META.get(owner_type)

    if isinstance(result, Entity) and result.id is not None and meta is not None:
        expected = {}
        for field in meta.fields:
            # _id's Mongo path isn't the Python attribute name ("id"); _match_clauses() below
            # already asserts it unconditionally.
            if field.name == "_id":
                continue
            val = field.extract_value(result)
            if val is not None:
                expected[field.path] = val

        return [
            PendingSearchSync(
                index_name=index_name,
                doc_id=result.id,
                kind=SyncKind.WRITE,
                expected_fields=expected,
            )
        ]

    if isinstance(result, InsertManyResult):
        return [
            PendingSearchSync(
                index_name=index_name,
                doc_id=doc_id,
                kind=SyncKind.WRITE,
            )
            for doc_id in result.inserted_ids
        ]

    return []


async def sync_search_entries(
    entries: list[PendingSearchSync],
    *,
    session: "AsyncClientSession | None",
) -> None:
    if not entries:
        return
    if session is None:
        await _wait_all(entries)
        return
    batch = _batch.get()
    if batch is None:
        raise UnmanagedSessionError(entries[0].kind)
    batch.extend(entries)


async def sync_search(
    index_name: str,
    doc_ids: list[PydanticObjectId],
    kind: SyncKind,
    *,
    session: "AsyncClientSession | None",
) -> None:
    """Manually waits for the given document ids to reach the expected search-sync state for
    `index_name`: present (by id only) for `SyncKind.WRITE`, absent for `SyncKind.DELETE`.
    Unlike `@synced`'s own verification, this doesn't check that specific field values are up
    to date - only that the document exists in (or is absent from) the index.

    Escape hatch for a write/delete that bypassed Entity's own wrapped methods (a raw pymongo
    bulk operation, for instance) and needs the same write-through verification `@synced`
    gives those methods for free.

    :param index_name: the Atlas Search index to verify against.
    :type index_name: str
    :param doc_ids: the document ids to wait on.
    :type doc_ids: list[PydanticObjectId]
    :param kind: which settlement state to wait for.
    :type kind: SyncKind
    :param session: the active Mongo session, if any. Requires an active
        `deferred_search_sync`/`@transactional` batch to enqueue into.
    :type session: AsyncClientSession | None
    :raises UnmanagedSessionError: if `session` is given but there's no active batch to
        enqueue into.
    :raises ExceptionGroup: wrapping a `DocumentNeverSearchableError`/
        `DocumentNeverUnsearchableError` per id that never settled.
    """
    entries = [PendingSearchSync(index_name, doc_id, kind) for doc_id in doc_ids]
    await sync_search_entries(entries, session=session)


@asynccontextmanager
async def deferred_search_sync() -> AsyncGenerator[list[PendingSearchSync]]:
    """Batches every search-sync verification made inside the block into a single wait at
    the end, instead of one wait per write/delete.

    Only batches writes/deletes made with an explicit `session=` - a write made without
    `session=` still waits immediately on its own, exactly as it always does, and gets no
    batching.

    :returns: an async context manager yielding the mutable list of pending syncs collected
        so far; writes/deletes made inside the block append to it automatically.
    :rtype: AsyncGenerator[list[PendingSearchSync]]
    :raises ExceptionGroup: on exit, wrapping a `DocumentNeverSearchableError`/
        `DocumentNeverUnsearchableError` per entry that never settled.
    """
    batch: list[PendingSearchSync] = []
    token = _batch.set(batch)
    try:
        yield batch
    finally:
        _batch.reset(token)
    await _wait_all(batch)


class _WaitGroup:
    def __init__(self, index_name: str, kind: SyncKind) -> None:
        self._index_name = index_name
        self._kind = kind
        self._pending: dict[PydanticObjectId, PendingSearchSync] = {}
        self._waiters: dict[PydanticObjectId, list[asyncio.Future[Exception | None]]] = {}
        self._task: asyncio.Task[None] | None = None
        self._total = 0

    def register(self, entry: PendingSearchSync) -> "asyncio.Future[Exception | None]":
        future: asyncio.Future[Exception | None] = asyncio.get_running_loop().create_future()
        # Latest entry per doc_id wins; every earlier waiter still resolves with it.
        self._pending[entry.doc_id] = entry
        self._waiters.setdefault(entry.doc_id, []).append(future)
        self._total += 1
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        return future

    async def _run(self) -> None:
        try:
            await self._poll_to_settlement()
        except Exception as exc:
            # A failure unrelated to any single document (e.g. an unregistered index) - every
            # waiter still pending shares the same cause, deduplicated by _wait_all.
            for doc_id in list(self._waiters):
                self._resolve(doc_id, exc)
        finally:
            del _wait_groups[(self._index_name, self._kind)]

    async def _poll_to_settlement(self) -> None:
        should_exist = self._kind is SyncKind.WRITE
        state = "searchable and up-to-date" if should_exist else "unsearchable"
        collection = _collection_for(self._index_name)
        log = logger.bind(index_name=self._index_name, collection=collection.name)

        async def settled() -> bool:
            await self._tick(should_exist)
            return not self._pending

        def on_retry(attempt: int) -> None:
            log.debug(f"{len(self._pending)} document(s) not yet {state}, retrying.", attempt=attempt)

        if await poll_until(settled, policy=get_polling_config().search_sync, on_retry=on_retry):
            log.info(f"{self._total} document(s) are {state}.")
            return

        for doc_id in list(self._pending):
            logger.bind(
                index_name=self._index_name,
                collection=collection.name,
                doc_id=str(doc_id),
            ).error(f"Document never became {state}.")
            exc: Exception = (
                DocumentNeverSearchableError(self._index_name, doc_id)
                if should_exist
                else DocumentNeverUnsearchableError(self._index_name, doc_id)
            )
            self._resolve(doc_id, exc)
        self._pending.clear()

    async def _tick(self, should_exist: bool) -> None:
        # Snapshot boundary: entries registering after this dispatch join the *next* tick,
        # never credited against a query that was sent before they existed.
        snapshot = dict(self._pending)
        if not snapshot:
            return

        matched_ids = await _matched_ids(self._index_name, list(snapshot.values()))
        settled_ids = matched_ids if should_exist else (set(snapshot) - matched_ids)
        for doc_id in settled_ids:
            if self._pending.get(doc_id) is snapshot[doc_id]:
                del self._pending[doc_id]
                self._resolve(doc_id, None)

    def _resolve(self, doc_id: PydanticObjectId, exc: Exception | None) -> None:
        for future in self._waiters.pop(doc_id, []):
            if not future.done():
                future.set_result(exc)


_wait_groups: dict[tuple[str, SyncKind], _WaitGroup] = {}


def _wait_group_for(index_name: str, kind: SyncKind) -> _WaitGroup:
    key = (index_name, kind)
    group = _wait_groups.get(key)
    if group is None:
        group = _WaitGroup(index_name, kind)
        _wait_groups[key] = group
    return group


async def _wait_all(entries: list[PendingSearchSync]) -> None:
    if not entries:
        return

    futures = [_wait_group_for(entry.index_name, entry.kind).register(entry) for entry in entries]
    results = await asyncio.gather(*futures)

    seen_ids: set[int] = set()
    exceptions: list[Exception] = []
    for exc in results:
        if exc is None or id(exc) in seen_ids:
            continue
        seen_ids.add(id(exc))
        exceptions.append(exc)

    if exceptions:
        raise ExceptionGroup("Search synchronization failed", exceptions)


def _collection_for(index_name: str) -> AsyncCollection[Mapping[str, Any]]:
    entity_class = _INDEX_TO_ENTITY.get(index_name)
    if entity_class is None:
        raise UnknownSearchIndexError(index_name)

    return entity_class.get_pymongo_collection()


class _IdProjection(BaseModel):
    id: PydanticObjectId = Field(alias="_id")
    model_config = ConfigDict(populate_by_name=True)


async def _matched_ids(index_name: str, entries: list[PendingSearchSync]) -> set[PydanticObjectId]:
    entity_class = _INDEX_TO_ENTITY[index_name]

    should_clauses: list[SearchQuery[Any] | dict[str, Any]] = []

    simple_ids = [entry.doc_id for entry in entries if not entry.expected_fields]
    if simple_ids:
        should_clauses.append({"in": {"path": "_id", "value": simple_ids}})

    should_clauses.extend(_match_clauses(entity_class, entry) for entry in entries if entry.expected_fields)

    projections = await entity_class.search().should(*should_clauses).project(_IdProjection).to_list()
    return {projection.id for projection in projections}


def _match_clauses(entity_class: "type[Entity]", entry: PendingSearchSync) -> "SearchQuery[Entity]":
    query = entity_class.search().filter_equals("_id", entry.doc_id)

    if entry.expected_fields:
        for path, expected_value in entry.expected_fields.items():
            if isinstance(expected_value, (list, set, tuple)):
                for item in expected_value:
                    if isinstance(item, str) and item:
                        query.phrase(path, item)
            elif isinstance(expected_value, str) and expected_value:
                query.phrase(path, expected_value)

    return query
