from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping
from functools import wraps
from typing import Any, ClassVar, Concatenate, Self, cast, overload

from beanie import BulkWriter, Document, WriteRules
from beanie.odm.actions import ActionDirections
from beanie.odm.enums import SortDirection
from pydantic import BaseModel
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.results import InsertManyResult

from .exceptions import (
    DuplicateSearchIndexError,
    EmptySearchIndexNameError,
    ProxiedMethodNotImplementedError,
    UnexpectedSearchableFieldError,
)
from .fields import get_searchable_fields
from .injection import _AmbientBulkWriter, _enable_session_injection
from .query import EntityFindMany, EntityFindOne, SearchQuery
from .registry import _ALL_ENTITIES, _ENTITY_SEARCH_META, _INDEX_TO_ENTITY, SearchMeta
from .sync import synced


# E/type[E] binds from the stub's own self/cls; a bare `...` stub (inferred return None)
# still matches since the input side only demands Awaitable[Any].
@overload
def _proxied[E: "Entity", **P](
    fn: Callable[Concatenate[E, P], Awaitable[Any]],
) -> Callable[Concatenate[E, P], Coroutine[Any, Any, E]]: ...


@overload
def _proxied[E: "Entity", **P](
    fn: Callable[Concatenate[type[E], P], Awaitable[Any]],
) -> Callable[Concatenate[type[E], P], Coroutine[Any, Any, InsertManyResult]]: ...


def _proxied(
    fn: Callable[Concatenate[Any, ...], Awaitable[Any]],
) -> Callable[Concatenate[Any, ...], Coroutine[Any, Any, Any]]:
    name = fn.__name__

    @wraps(fn)
    async def wrapper(owner: Any, *args: Any, **kwargs: Any) -> Any:
        owner_type = owner if isinstance(owner, type) else type(owner)

        # __dict__, not getattr: getattr(Document, name) on a classmethod binds cls=Document,
        # which would shift every positional argument by one when called with `owner`.
        raw_method = Document.__dict__.get(name)
        if raw_method is None:  # pragma: no cover (Document always implements these 5 names)
            raise ProxiedMethodNotImplementedError(owner_type, name)

        if isinstance(raw_method, classmethod):
            return await raw_method.__func__(owner_type, *args, **kwargs)

        return await raw_method(owner, *args, **kwargs)

    return wrapper


def _is_abstract_root(cls: "type[Entity]") -> bool:
    # An abstract intermediate subclass (its own is_root=True) has no collection to register.
    settings = cls.__dict__.get("Settings")
    return bool(getattr(settings, "is_root", False)) if settings else False


def _resolve_search_index(cls: "type[Entity]") -> str | None:
    effective_settings = getattr(cls, "Settings", None)
    index: str | None = getattr(effective_settings, "search_index", None) if effective_settings else None
    if index is None:
        return None

    index = index.strip()
    if not index:
        raise EmptySearchIndexNameError()
    return index


def _register_search_index(cls: "type[Entity]") -> None:
    index = _resolve_search_index(cls)
    indexed = get_searchable_fields(cls)
    has_domain_fields = len(indexed) > 1

    # A searchable() field needs a search_index, or it would silently never sync.
    if has_domain_fields and index is None:
        raise UnexpectedSearchableFieldError(cls, indexed)

    if index is None or not has_domain_fields:
        return

    existing = _INDEX_TO_ENTITY.get(index)
    if existing is not None and existing is not cls:
        raise DuplicateSearchIndexError(index, cls, existing)

    _INDEX_TO_ENTITY[index] = cls
    _ENTITY_SEARCH_META[cls] = SearchMeta(index=index, fields=indexed)


class Entity(Document):
    """Base document model for the canterlot.hoodie framework.

    Subclassing Entity, instead of Beanie's own Document directly, opts a model into four
    things: auto-registration for database initialization (see `init_hoodie`), write-through
    Atlas Search sync on every insert/save/replace/update/insert_many (see `@synced` and
    `searchable`), ambient Mongo session injection, so a write made inside an active
    `@transactional` body doesn't need `session` threaded through by hand, and a fluent Atlas
    Search query builder bound to the entity's own index (see `search`).

    :raises EmptySearchIndexNameError: at subclass definition time, if `Settings.search_index`
        is set to a blank string.
    :raises UnexpectedSearchableFieldError: at subclass definition time, if the subclass has
        searchable() fields but no `Settings.search_index` configured.
    :raises DuplicateSearchIndexError: at subclass definition time, if `Settings.search_index`
        reuses a name another Entity subclass already registered, and this subclass also
        declares at least one `searchable()` field.
    """

    _find_many_query_class: ClassVar[type] = EntityFindMany
    _find_one_query_class: ClassVar[type] = EntityFindOne

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)

        _enable_session_injection(cls)

        if _is_abstract_root(cls):
            return

        _ALL_ENTITIES.add(cls)
        _register_search_index(cls)

    @overload
    @classmethod
    def find_many(
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: None = None,
        skip: int | None = None,
        limit: int | None = None,
        sort: str | list[tuple[str, SortDirection]] | None = None,
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        lazy_parse: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindMany[Self]": ...
    @overload
    @classmethod
    def find_many[P: BaseModel](
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: type[P] | None = None,
        skip: int | None = None,
        limit: int | None = None,
        sort: str | list[tuple[str, SortDirection]] | None = None,
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        lazy_parse: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindMany[P]": ...
    @classmethod
    def find_many(cls, *args: Any, **kwargs: Any) -> "EntityFindMany[Any]":
        """Find many documents by criteria.
        Returns an EntityFindMany query object, with `.search(...)` available for a further
        Atlas Search step (through a Link field, or self-scoped by this call's own Mongo
        filter).

        :param args: search criteria.
        :type args: Mapping[Any, Any] | bool
        :param skip: the number of documents to omit.
        :type skip: int | None
        :param limit: the maximum number of results to return.
        :type limit: int | None
        :param sort: a key or a list of (key, direction) pairs specifying the sort order for
            this query.
        :type sort: str | list[tuple[str, SortDirection]] | None
        :type projection_model: type[BaseModel] | None
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :type ignore_cache: bool
        :type lazy_parse: bool
        :param pymongo_kwargs: pymongo native parameters for find operation (if Document class
            contains links, this parameter must fit the respective parameter of the aggregate
            MongoDB function).
        :type pymongo_kwargs: Any
        :returns: query instance, search-query capable via `.search(...)`.
        :rtype: EntityFindMany[Any]
        """
        return cast("EntityFindMany[Any]", super().find_many(*args, **kwargs))

    @overload
    @classmethod
    def find(
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: None = None,
        skip: int | None = None,
        limit: int | None = None,
        sort: str | list[tuple[str, SortDirection]] | None = None,
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        lazy_parse: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindMany[Self]": ...
    @overload
    @classmethod
    def find[P: BaseModel](
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: type[P],
        skip: int | None = None,
        limit: int | None = None,
        sort: str | list[tuple[str, SortDirection]] | None = None,
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        lazy_parse: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindMany[P]": ...
    @classmethod
    def find(cls, *args: Any, **kwargs: Any) -> "EntityFindMany[Any]":
        """Find documents by criteria.

        Alias for `find_many`, matching Beanie's own naming. Returns an EntityFindMany query
        object, with `.search(...)` available for a further Atlas Search step (through a Link
        field, or self-scoped by this call's own Mongo filter).

        :param args: search criteria.
        :type args: Mapping[Any, Any] | bool
        :param skip: the number of documents to omit.
        :type skip: int | None
        :param limit: the maximum number of results to return.
        :type limit: int | None
        :param sort: a key or a list of (key, direction) pairs specifying the sort order for
            this query.
        :type sort: str | list[tuple[str, SortDirection]] | None
        :type projection_model: type[BaseModel] | None
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :type ignore_cache: bool
        :type lazy_parse: bool
        :param pymongo_kwargs: pymongo native parameters for find operation (if Document class
            contains links, this parameter must fit the respective parameter of the aggregate
            MongoDB function).
        :type pymongo_kwargs: Any
        :returns: query instance, search-query capable via `.search(...)`.
        :rtype: EntityFindMany[Any]
        """
        return cast("EntityFindMany[Any]", super().find(*args, **kwargs))

    @overload
    @classmethod
    def find_one(
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: None = None,
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindOne[Self]": ...
    @overload
    @classmethod
    def find_one[P: BaseModel](
        cls,
        *args: Mapping[Any, Any] | bool,
        projection_model: type[P],
        session: AsyncClientSession | None = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
        with_children: bool = False,
        nesting_depth: int | None = None,
        nesting_depths_per_field: dict[str, int] | None = None,
        **pymongo_kwargs: Any,
    ) -> "EntityFindOne[P]": ...
    @classmethod
    def find_one(cls, *args: Any, **kwargs: Any) -> "EntityFindOne[Any]":
        """Find one document by criteria.
        Returns an EntityFindOne query object, with `.search(link_field)` available for a
        further Atlas Search step through a Link field, scoped by this call's own Mongo filter
        and capped to at most one owner document.
        When awaited this will either return a document or None if no document exists for the
        search criteria.

        :param args: search criteria.
        :type args: Mapping[Any, Any] | bool
        :type projection_model: type[BaseModel] | None
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :type ignore_cache: bool
        :param pymongo_kwargs: pymongo native parameters for find operation (if Document class
            contains links, this parameter must fit the respective parameter of the aggregate
            MongoDB function).
        :type pymongo_kwargs: Any
        :returns: query instance, search-query capable via `.search(link_field)`.
        :rtype: EntityFindOne[Any]
        """
        return cast("EntityFindOne[Any]", super().find_one(*args, **kwargs))

    @classmethod
    def search(cls) -> "SearchQuery[Self]":
        """Starts a fluent Atlas Search query bound to this Entity's own search index.

        Chain `text`/`filter_in`/`filter_equals`/`filter_not_equals`/`phrase`/`should`/`facet`
        clauses, then execute with `to_list()`/`paginate()`.

        :returns: a new `SearchQuery` bound to this Entity's collection and search index.
        :rtype: SearchQuery[Self]
        :raises EntityNotSearchableError: if this Entity has no `Settings.search_index`
            configured, or has no `searchable()` domain fields.
        """
        return SearchQuery(cls)

    @synced
    @_proxied
    async def insert(
        self,
        *,
        link_rule: WriteRules = WriteRules.DO_NOTHING,
        session: AsyncClientSession | None = None,
        skip_actions: list[ActionDirections | str] | None = None,
    ):
        """Insert the document (self) into the collection.

        Search-synced automatically after a successful call (see @synced). Omit session
        inside an active @transactional body; the ambient session is auto-injected.

        :param link_rule: if WriteRules.WRITE, insert Link Documents to the db.
        :type link_rule: WriteRules
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :returns: self
        :rtype: Self
        :raises InvalidSessionTypeError: if session is given but isn't an AsyncClientSession -
            only checked when this write's search-sync isn't skipped (see `@synced`).
        :raises UnmanagedSessionError: if session is given but there's no active
            deferred_search_sync/@transactional batch to enqueue into.
        :raises ExceptionGroup: wrapping a DocumentNeverSearchableError per document that
            never became searchable within the polling window.
        """

    @synced
    @_proxied
    async def save(
        self,
        session: AsyncClientSession | None = None,
        link_rule: WriteRules = WriteRules.DO_NOTHING,
        ignore_revision: bool = False,
        **kwargs: Any,
    ):
        """Update an existing model in the database, or insert it if it does not yet exist.

        Search-synced automatically after a successful save (see @synced). Omit session
        inside an active @transactional body; the ambient session is auto-injected.

        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :param link_rule: rules for how to deal with links on writing.
        :type link_rule: WriteRules
        :param ignore_revision: force save even if the revision id doesn't match.
        :type ignore_revision: bool
        :returns: self
        :rtype: Self
        :raises InvalidSessionTypeError: if session is given but isn't an AsyncClientSession -
            only checked when this write's search-sync isn't skipped (see `@synced`).
        :raises UnmanagedSessionError: if session is given but there's no active
            deferred_search_sync/@transactional batch to enqueue into.
        :raises ExceptionGroup: wrapping a DocumentNeverSearchableError per document that
            never became searchable within the polling window.
        """

    @synced
    @_proxied
    async def replace(
        self,
        ignore_revision: bool = False,
        session: AsyncClientSession | None = None,
        bulk_writer: BulkWriter | None = None,
        link_rule: WriteRules = WriteRules.DO_NOTHING,
        skip_actions: list[ActionDirections | str] | None = None,
    ):
        """Fully update the document in the database.

        Search-synced automatically after a successful replace (see @synced). Passing
        bulk_writer intentionally skips this: bulk writes prioritize ingestion throughput, and
        the caller takes on responsibility for the index's eventual consistency. Inside an
        active @transactional body, build the writer with `Entity.bulk_writer()`: a bare
        `BulkWriter()` commits outside the transaction.

        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :param ignore_revision: force replace even if the revision id doesn't match.
        :type ignore_revision: bool
        :param bulk_writer: Beanie bulk writer.
        :type bulk_writer: BulkWriter | None
        :returns: self
        :rtype: Self
        :raises InvalidSessionTypeError: if session is given but isn't an AsyncClientSession -
            only checked when this write's search-sync isn't skipped (see `@synced`).
        :raises UnmanagedSessionError: if session is given but there's no active
            deferred_search_sync/@transactional batch to enqueue into.
        :raises ExceptionGroup: wrapping a DocumentNeverSearchableError per document that
            never became searchable within the polling window.
        """

    @synced
    @_proxied
    async def update(
        self,
        *args: dict[Any, Any] | Mapping[Any, Any],
        ignore_revision: bool = False,
        session: AsyncClientSession | None = None,
        bulk_writer: BulkWriter | None = None,
        skip_actions: list[ActionDirections | str] | None = None,
        **pymongo_kwargs: Any,
    ):
        """Partially update the document in the database.

        Search-synced automatically after a successful update (see @synced). Passing
        bulk_writer intentionally skips this: bulk writes prioritize ingestion throughput, and
        the caller takes on responsibility for the index's eventual consistency. Inside an
        active @transactional body, build the writer with `Entity.bulk_writer()`: a bare
        `BulkWriter()` commits outside the transaction.

        :param args: the modifications to apply.
        :type args: dict[Any, Any] | Mapping[Any, Any]
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :param ignore_revision: force update even if the revision id doesn't match.
        :type ignore_revision: bool
        :param bulk_writer: Beanie bulk writer.
        :type bulk_writer: BulkWriter | None
        :param pymongo_kwargs: native pymongo parameters for the update operation.
        :type pymongo_kwargs: Any
        :returns: self
        :rtype: Self
        :raises InvalidSessionTypeError: if session is given but isn't an AsyncClientSession -
            only checked when this write's search-sync isn't skipped (see `@synced`).
        :raises UnmanagedSessionError: if session is given but there's no active
            deferred_search_sync/@transactional batch to enqueue into.
        :raises ExceptionGroup: wrapping a DocumentNeverSearchableError per document that
            never became searchable within the polling window.
        """

    @classmethod
    def bulk_writer(
        cls,
        session: AsyncClientSession | None = None,
        ordered: bool = True,
        bypass_document_validation: bool | None = False,
        comment: Any | None = None,
    ) -> BulkWriter:
        """Returns a BulkWriter bound to this Entity, which commits through the ambient
        `@transactional` session when no `session` is given.

        Use this instead of a bare `BulkWriter()` inside a `@transactional` body: a bare writer
        carries no session, so it commits outside the transaction. Like any bulk write, it skips
        search-sync verification.

        :param session: pymongo session; the ambient transaction session is used when omitted.
        :type session: AsyncClientSession | None
        :param ordered: if True, operations run serially and stop at the first failure.
        :type ordered: bool
        :param bypass_document_validation: if True, opts the write out of document-level
            validation.
        :type bypass_document_validation: bool | None
        :param comment: a comment attached to the bulk write command.
        :type comment: Any | None
        :returns: the bulk writer.
        :rtype: BulkWriter
        """
        return _AmbientBulkWriter(session, ordered, cls, bypass_document_validation, comment)

    @classmethod
    @synced
    @_proxied
    async def insert_many(
        cls,
        documents: Iterable[Self],
        session: AsyncClientSession | None = None,
        link_rule: WriteRules = WriteRules.DO_NOTHING,
        **pymongo_kwargs: Any,
    ):
        """Insert many documents into the collection.

        Every inserted document is search-synced automatically (see @synced). Omit session
        inside an active @transactional body; the ambient session is auto-injected.

        :param documents: the documents to insert.
        :type documents: Iterable[Self]
        :param session: pymongo session.
        :type session: AsyncClientSession | None
        :param link_rule: how to manage link fields.
        :type link_rule: WriteRules
        :returns: the insert-many result.
        :rtype: InsertManyResult
        :raises InvalidSessionTypeError: if session is given but isn't an AsyncClientSession -
            only checked when this write's search-sync isn't skipped (see `@synced`).
        :raises UnmanagedSessionError: if session is given but there's no active
            deferred_search_sync/@transactional batch to enqueue into.
        :raises ExceptionGroup: wrapping a DocumentNeverSearchableError per inserted document
            that never became searchable within the polling window.
        """
