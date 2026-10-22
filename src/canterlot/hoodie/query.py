from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Generator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Self, TypedDict, cast, overload

from beanie import BackLink, Link, PydanticObjectId
from beanie.odm.queries.delete import DeleteMany, DeleteOne
from beanie.odm.queries.find import FindMany, FindOne
from beanie.odm.utils.projection import get_projection
from pydantic import BaseModel
from pymongo.results import DeleteResult

from .exceptions import EntityNotSearchableError, NotALinkFieldError, SearchWithinTransactionError
from .injection import (
    _AmbientAggregationQuery,
    _AmbientDeleteMany,
    _AmbientDeleteOne,
    _AmbientSessionMixin,
    _AmbientUpdateMany,
    _AmbientUpdateOne,
)
from .registry import _CURRENT_SESSION, _ENTITY_SEARCH_META, is_search_enabled

if TYPE_CHECKING:
    from .entity import Entity

FacetType = Literal["string", "number", "date"]

_SCORE_FIELD = "__hoodie_search_score__"

# Beanie overrides Link fields with an ExpressionField(str) at runtime (invisible to mypy), so a str is accepted too.
type LinkFieldRef = str | Link[Any] | BackLink[Any]


class FacetBucket(TypedDict):
    """One bucket of an Atlas Search facet result, as returned under `SearchPage.facets`."""

    _id: Any
    count: int


class SearchPage[E](TypedDict):
    """A page of search results, as returned by `SearchQuery.paginate`/`ForeignSearchQuery.paginate`."""

    items: list[E]
    total_items: int
    facets: NotRequired[dict[str, list[FacetBucket]]]


@dataclass(frozen=True, slots=True)
class Scored[E]:
    """An entity (or other parsed result) paired with its Atlas Search relevance score."""

    item: E
    score: float


class BaseSearchQuery[T: BaseModel, ItemT = Any](ABC):
    """Fluent Atlas Search clause builder bound to a single target index.

    Shared base for `SearchQuery` (searches a single Entity's own index, either unscoped or
    pre-scoped by an external Mongo filter) and `ForeignSearchQuery` (searches a Link target's
    index, scoped by a referencing entity's own query). Chain `text`/`filter_in`/`filter_equals`/
    `filter_not_equals`/`phrase`/`should`/`facet` to build up the query; `to_compound()`/
    `to_pipeline()` expose the assembled query as plain pipeline-stage dicts, for a caller that
    needs to run or further compose the aggregation itself, or nest this query inside another
    one via `should()`.

    Parameterized by `T`, the model results are ultimately projected onto, and `ItemT`, each
    result's own shape - `T` itself for `SearchQuery`, the referencing entity `R` for
    `ForeignSearchQuery`.
    `ItemT` defaults to `Any`, so a caller can hold a bare `BaseSearchQuery[T]` reference
    regardless of which concrete subclass produced it. Code written generically against
    `BaseSearchQuery[T]` can still execute a query and get back a genuine (if `ItemT`-erased)
    result shape without knowing which subclass it holds: `__aiter__`/`__anext__`/`to_list()`
    are fully shared here, built on the abstract `_open_cursor()`/`_parse_doc()` hooks (mirroring
    Beanie's own `BaseCursorQuery`), while `paginate()` is declared here abstractly and each
    subclass overrides it with its own more precise return type, which is what a caller holding
    the concrete subclass type actually sees. `project()` and `scored()` are each subclass's own
    methods, not declared here - see the note above `__aiter__` below.

    :raises EntityNotSearchableError: at construction time, if `entity_type` has no
        `Settings.search_index` configured.
    """

    def __init__(self, entity_type: "type[T]") -> None:
        # entity_type is always a real Entity subtype in practice; T binds to the looser BaseModel
        # so SearchQuery.project() can re-parameterize the query onto an arbitrary projection model.
        owner = cast("type[Entity]", entity_type)
        meta = _ENTITY_SEARCH_META.get(owner)
        if meta is None:
            raise EntityNotSearchableError(owner)

        self._entity_type = owner
        self._index = meta.index
        self._model: type[Any] = entity_type
        self._must: list[dict[str, Any]] = []
        self._filter: list[dict[str, Any]] = []
        self._must_not: list[dict[str, Any]] = []
        self._should: list[dict[str, Any]] = []
        self._minimum_should_match = 1
        self._facets: dict[str, dict[str, Any]] = {}
        self._with_score = False
        self._limit: int | None = None
        self._cursor: AsyncIterator[dict[str, Any]] | None = None
        self._exhausted = False

    def text(self, path: str | list[str], query: str, *, fuzzy: bool = False) -> Self:
        """Adds a `must` full-text clause.

        :param path: the field (or fields) to search.
        :type path: str | list[str]
        :param query: the search string.
        :type query: str
        :param fuzzy: whether to allow fuzzy (typo-tolerant) matching.
        :type fuzzy: bool
        :returns: self, for chaining.
        :rtype: Self
        """
        clause: dict[str, Any] = {"query": query, "path": path}
        if fuzzy:
            clause["fuzzy"] = {}
        self._must.append({"text": clause})
        return self

    def phrase(self, path: str, query: str) -> Self:
        """Adds a `must` exact-phrase clause.

        :param path: the field to match against.
        :type path: str
        :param query: the phrase to match.
        :type query: str
        :returns: self, for chaining.
        :rtype: Self
        """
        self._must.append({"phrase": {"path": path, "query": query}})
        return self

    def filter_in(self, path: str, values: list[Any]) -> Self:
        """Adds a non-scoring `filter` clause matching any of `values`.

        :param path: the field to filter on.
        :type path: str
        :param values: the accepted values.
        :type values: list[Any]
        :returns: self, for chaining.
        :rtype: Self
        """
        self._filter.append({"in": {"path": path, "value": values}})
        return self

    def filter_equals(self, path: str, value: Any) -> Self:
        """Adds a non-scoring `filter` clause for an exact single value.

        :param path: the field to filter on.
        :type path: str
        :param value: the required value.
        :type value: Any
        :returns: self, for chaining.
        :rtype: Self
        """
        self._filter.append({"equals": {"path": path, "value": value}})
        return self

    def filter_not_equals(self, path: str, value: Any) -> Self:
        """Adds a non-scoring `mustNot` clause excluding an exact single value.

        :param path: the field to filter on.
        :type path: str
        :param value: the excluded value.
        :type value: Any
        :returns: self, for chaining.
        :rtype: Self
        """
        self._must_not.append({"equals": {"path": path, "value": value}})
        return self

    def should(
        self,
        *clauses: "BaseSearchQuery[Any] | dict[str, Any]",
        minimum_should_match: int = 1,
    ) -> Self:
        """Adds one or more `should` clauses, at least `minimum_should_match` of which must match.

        :param clauses: each is either a nested search query (wrapped as its own `compound`
            sub-clause) or a raw Atlas Search clause dict, used as-is.
        :type clauses: BaseSearchQuery[Any] | dict[str, Any]
        :param minimum_should_match: how many of this query's accumulated `should` clauses
            (from every `should()` call so far) must match. Each call's value replaces
            whatever a previous `should()` call set - it does not combine with it.
        :type minimum_should_match: int
        :returns: self, for chaining.
        :rtype: Self
        """
        for clause in clauses:
            self._should.append({"compound": clause.to_compound()} if isinstance(clause, BaseSearchQuery) else clause)
        self._minimum_should_match = minimum_should_match
        return self

    def facet(self, name: str, path: str, facet_type: FacetType, **opts: Any) -> Self:
        """Adds an Atlas Search facet definition, bucketing results by `path` alongside the
        query's own compound match.

        :param name: the facet's name, used as its key in `SearchPage.facets`.
        :type name: str
        :param path: the field's own path, as declared with `searchable(facetable=True)`.
        :type path: str
        :param facet_type: the Atlas facet type: "string", "number", or "date".
        :type facet_type: FacetType
        :param opts: extra facet definition options forwarded as-is (e.g. `boundaries`,
            `numBuckets`, `default`).
        :type opts: Any
        :returns: self, for chaining.
        :rtype: Self
        """
        self._facets[name] = {"type": facet_type, "path": path, **opts}
        return self

    def limit(self, limit: int) -> Self:
        """Caps the number of candidates this query considers, from the top of Atlas Search's
        own relevance ranking.

        Also caps what `paginate()` pages through: with a limit of `n`, `paginate(page, size)`
        only ever walks the top `n` results, and its `total_items` is clamped to `n` even if
        more documents actually match.

        :param limit: the maximum number of top-ranked candidates to keep.
        :type limit: int
        :returns: self, for chaining.
        :rtype: Self
        """
        self._limit = limit
        return self

    def to_compound(self) -> dict[str, Any]:
        """Assembles this query's clauses into a single Atlas Search `compound` operator body.

        :returns: the `compound` dict, with `must`/`filter`/`mustNot`/`should` present only when
            non-empty (`minimumShouldMatch` included alongside a non-empty `should`).
        :rtype: dict[str, Any]
        """
        compound: dict[str, Any] = {}
        if self._must:
            compound["must"] = self._must
        if self._filter:
            compound["filter"] = self._filter
        if self._must_not:
            compound["mustNot"] = self._must_not
        if self._should:
            compound["should"] = self._should
            compound["minimumShouldMatch"] = self._minimum_should_match
        return compound

    def to_pipeline(self) -> list[dict[str, Any]]:
        """Builds this query's aggregation pipeline stages, without executing it.

        :returns: the pipeline's stage dicts, ready to append to or run via
            `Entity.aggregate(...)`/a raw pymongo collection.
        :rtype: list[dict[str, Any]]
        """
        pipeline: list[dict[str, Any]] = [{"$search": self._search_stage()}]
        if self._limit is not None:
            pipeline.append({"$limit": self._limit})
        project_stage = self._project_stage()
        if project_stage is not None:
            pipeline.append(project_stage)
        return pipeline

    # scored() lives on each subclass: its self-type overloads can't be expressed as one signature on this base.

    def __aiter__(self) -> Self:
        """Returns self as the async iterator `async for` drives - see `__anext__`."""
        return self

    async def __anext__(self) -> "ItemT":
        """Pulls the next matching result, lazily opening the underlying aggregate cursor on
        first call and caching it for the rest of this iteration.

        :returns: the next `ItemT` (or `Scored[ItemT]`, if `.scored()` was called).
        :rtype: ItemT
        :raises StopAsyncIteration: once every matching result has been returned.
        :raises SearchWithinTransactionError: if called from within an active `@transactional`
            body - Atlas Search cannot run inside a multi-document transaction.
        """
        if self._exhausted:
            raise StopAsyncIteration
        if self._cursor is None:
            cursor = await self._open_cursor()
            if cursor is None:
                self._exhausted = True
                raise StopAsyncIteration
            self._cursor = cursor
        try:
            doc = await anext(self._cursor)
        except StopAsyncIteration:
            self._exhausted = True
            raise
        return self._parse_doc(doc)

    @abstractmethod
    async def _open_cursor(self) -> "AsyncIterator[dict[str, Any]] | None": ...

    @abstractmethod
    def _parse_doc(self, doc: "dict[str, Any]") -> "ItemT": ...

    async def to_list(self) -> "list[ItemT]":
        """Runs this query and returns every matching result as a list.

        :returns: matching results as `ItemT` (or `Scored[ItemT]`, if `.scored()` was called),
            in Atlas Search's own relevance order, capped by `.limit()` if set.
        :rtype: list[ItemT]
        :raises SearchWithinTransactionError: if called from within an active `@transactional`
            body - Atlas Search cannot run inside a multi-document transaction.
        """
        return [item async for item in self]

    @abstractmethod
    async def paginate(self, page: int, limit: int) -> "SearchPage[ItemT]":
        """Runs this query for a single page of results, alongside its total match count and
        any facet buckets configured via `facet(...)`.

        :param page: the 1-indexed page number.
        :type page: int
        :param limit: the page size, and (together with any `.limit()` cap already configured)
            how many top-ranked candidates are actually paginated through.
        :type limit: int
        :returns: a `SearchPage` of `ItemT` (or `Scored[ItemT]` if `.scored()` was called).
            See the concrete subclass's own `paginate` for what `ItemT` resolves to.
        :rtype: SearchPage[ItemT]
        :raises SearchWithinTransactionError: if called from within an active `@transactional`
            body - Atlas Search cannot run inside a multi-document transaction.
        """

    def _ensure_not_within_transaction(self) -> None:
        """Atlas Search cannot run inside a multi-document transaction."""
        if _CURRENT_SESSION.get() is not None:
            raise SearchWithinTransactionError(self._index)

    def _search_stage(self, *, count: bool = False) -> dict[str, Any]:
        stage: dict[str, Any] = {"index": self._index}
        compound = self.to_compound()
        if self._facets:
            stage["facet"] = {"operator": {"compound": compound}, "facets": dict(self._facets)}
        else:
            stage["compound"] = compound
        if count:
            # Atlas defaults to an approximate lowerBound count; paginate() needs the exact
            # total for its own total_items to be trustworthy, not just a rough estimate.
            stage["count"] = {"type": "total"}
        return stage

    def _project_stage(self) -> dict[str, Any] | None:
        if self._model is self._entity_type:
            return None

        projection = get_projection(self._model)
        return {"$project": projection} if projection else None

    def _build_items_stages(self, page: int, limit: int) -> list[dict[str, Any]]:
        stages: list[dict[str, Any]] = []
        if self._limit is not None:
            stages.append({"$limit": self._limit})
        stages.extend([{"$skip": (page - 1) * limit}, {"$limit": limit}])

        project_stage = self._project_stage()
        if project_stage is not None:
            stages.append(project_stage)
        if self._with_score:
            stages.append({"$set": {_SCORE_FIELD: {"$meta": "searchScore"}}})

        return stages

    def _build_facet_pipeline(self, items_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"$search": self._search_stage(count=True)},
            {
                "$facet": {
                    "items": items_stages,
                    "meta": [{"$replaceWith": "$$SEARCH_META"}, {"$limit": 1}],
                },
            },
        ]

    def _extract_total_items(self, meta: dict[str, Any]) -> int:
        total_items: int = meta.get("count", {}).get("total", 0)
        return min(total_items, self._limit) if self._limit is not None else total_items

    def _extract_facets(self, meta: dict[str, Any]) -> dict[str, list[Any]]:
        return {name: bucket_result.get("buckets", []) for name, bucket_result in meta.get("facet", {}).items()}

    def _parse(self, doc: dict[str, Any]) -> "T | Scored[T]":
        if not self._with_score:
            return cast(T, self._model.model_validate(doc))

        score: float = doc.pop(_SCORE_FIELD)
        return Scored(item=cast(T, self._model.model_validate(doc)), score=score)


class SearchQuery[E: BaseModel, ItemT = E](BaseSearchQuery[E, ItemT]):
    """Fluent Atlas Search query builder bound to a single Entity's own search index.

    Obtained via `Entity.search()` (unscoped), or via `EntityFindMany.search()` called with no
    `link_field` (scoped by that call's own Mongo filter).
    Chain `text`/`filter_in`/`filter_equals`/`filter_not_equals`/`phrase`/`should`/`facet`/
    `project`/`scored`/`limit` to build up the query, then run it with `to_list()`, `async for`,
    or `paginate()`. Each clause method mutates and returns `self` for chaining.

    `ItemT` (defaulting to `E`) tracks whether `.scored()` has been called, wrapping results in
    `Scored[E]` once it has - see `scored()`.

    :raises EntityNotSearchableError: at construction time, if `entity_type` has no
        `Settings.search_index` configured.
    """

    def __init__(self, entity_type: "type[E]", *, scope_filter: "Mapping[str, Any] | None" = None) -> None:
        """
        :param entity_type: the Entity subclass whose own search index this query runs against.
        :type entity_type: type[E]
        :param scope_filter: an already-encoded Mongo filter (as returned by a Beanie query's
            own `get_filter_query()`) to pre-scope this query's results by, before any Atlas
            Search clause runs. Not meant to be passed directly by ordinary callers - lets a
            caller scope an entity's own index by an arbitrary Mongo match that Atlas's own
            `filter`/`compound` clauses can't express (since `$search` must be the pipeline's
            first stage).
        :type scope_filter: Mapping[str, Any] | None
        """
        super().__init__(entity_type)
        self._scope_filter = scope_filter

    async def _resolve_scope_ids(self) -> "list[Any] | None":
        if self._scope_filter is None:
            return None
        return await self._entity_type.get_pymongo_collection().distinct("_id", self._scope_filter)

    @overload
    def project(self, projection_model: None) -> Self: ...
    @overload
    def project[P: BaseModel](self, projection_model: "type[P]") -> "SearchQuery[P]": ...

    def project(self, projection_model: "type[BaseModel] | None") -> "SearchQuery[Any]":
        """Narrows results to the given projection model instead of the full entity.

        Re-parameterizes this query's own static element type onto `projection_model`, so
        `to_list()`/`paginate()` are typed as returning the projection, not the full entity,
        past this call.

        :param projection_model: the Pydantic model to project onto, or None to leave the
            query's current projection (or lack of one) unchanged.
        :type projection_model: type[BaseModel] | None
        :returns: self, re-typed as `SearchQuery[projection_model]` (or unchanged, for None).
        :rtype: SearchQuery[Any]
        """
        if projection_model is not None:
            self._model = projection_model
        return self

    @overload
    def scored(self: "SearchQuery[E, E]") -> "SearchQuery[E, Scored[E]]": ...
    @overload
    def scored(self: "SearchQuery[E, Scored[E]]") -> "SearchQuery[E, Scored[E]]": ...

    def scored(self) -> "SearchQuery[E, Any]":
        """Wraps each result in a `Scored`, carrying its Atlas Search relevance score, once this
        query is run via `to_list()`/`async for`/`paginate()`. Calling it again is a no-op, not
        a double wrap.

        :returns: self, re-typed as `SearchQuery[E, Scored[E]]`.
        :rtype: SearchQuery[E, Any]
        """
        self._with_score = True
        return cast("SearchQuery[E, Any]", self)

    async def _open_cursor(self) -> "AsyncIterator[dict[str, Any]] | None":
        self._ensure_not_within_transaction()

        ids = await self._resolve_scope_ids()
        if ids is not None:
            if not ids:
                return None
            self.filter_in("_id", ids)

        pipeline = self.to_pipeline()
        if self._with_score:
            pipeline.append({"$set": {_SCORE_FIELD: {"$meta": "searchScore"}}})

        return self._entity_type.aggregate(pipeline)

    def _parse_doc(self, doc: "dict[str, Any]") -> "Any":
        return self._parse(doc)

    async def paginate(self, page: int, limit: int) -> "SearchPage[ItemT]":
        """Runs this query for a single page of results, alongside its total match count and
        any facet buckets configured via `facet(...)`.

        :param page: the 1-indexed page number.
        :type page: int
        :param limit: the page size, and (together with any `.limit()` cap already configured)
            how many top-ranked candidates are actually paginated through.
        :type limit: int
        :returns: a `SearchPage` with `items`, `total_items`, and `facets` when this query has
            any facet definitions. Empty (zero-bucket facets included), without ever issuing a
            `$search` call, if this query has a `scope_filter` that currently matches nothing.
        :rtype: SearchPage[ItemT]
        :raises SearchWithinTransactionError: if called from within an active `@transactional`
            body - Atlas Search cannot run inside a multi-document transaction.
        """
        self._ensure_not_within_transaction()

        ids = await self._resolve_scope_ids()
        if ids is not None:
            if not ids:
                return _empty_page(self._facets)
            self.filter_in("_id", ids)

        pipeline = self._build_facet_pipeline(self._build_items_stages(page, limit))

        result = await self._entity_type.aggregate(pipeline).to_list()
        facet = result[0]
        meta = facet["meta"][0] if facet["meta"] else {}

        result_page: SearchPage[Any] = {
            "items": [self._parse(doc) for doc in facet["items"]],
            "total_items": self._extract_total_items(meta),
        }
        if self._facets:
            result_page["facets"] = self._extract_facets(meta)
        return result_page


def _empty_page(facets: dict[str, dict[str, Any]]) -> "SearchPage[Any]":
    page: SearchPage[Any] = {"items": [], "total_items": 0}
    if facets:
        page["facets"] = {name: [] for name in facets}
    return page


class ForeignSearchQuery[R: BaseModel, T: BaseModel, ItemT = R](BaseSearchQuery[T, ItemT]):
    """Fluent Atlas Search query builder that searches a Link target's index, scoped by a
    referencing entity's own `.find()`/`.find_one()` query.

    Obtained via `EntityFindMany.search(link_field)`/`EntityFindOne.search(link_field)`. Chain
    the same clauses as `SearchQuery` (`text`/`filter_in`/`filter_equals`/`filter_not_equals`/
    `phrase`/`should`/`facet`/`scored`/`limit`, but not `project`), then run it with `to_list()`,
    `async for`, or `paginate()` - all three yield the *referencing* entity `R` (or `Scored[R]`
    once `.scored()` is called), with its searched Link field populated in place with the
    matching target `T`, the same way Beanie's own `fetch_links=True` leaves a `T` in a
    `Link[T]`-annotated field. A result is a read model: do not `save()` it.

    `ItemT` (defaulting to `R`) tracks whether `.scored()` has been called - see `scored()`.

    Assumes at most one scoped `R` document references a given target id; if more than one does,
    only the last one fetched is kept. Enforced at runtime when built from `.find_one(...)` (see
    `EntityFindOne.search`), which caps owner resolution to at most one document, matching
    `find_one`'s own single-document semantics; not enforced when built from `.find(...)`.

    :raises NotALinkFieldError: at construction time, if `link_field` isn't a Link/BackLink
        field on the scope query's own `document_model`.
    :raises EntityNotSearchableError: at construction time, if the Link's target type has no
        `Settings.search_index` configured.
    """

    def __init__(self, scope: "FindMany[R] | FindOne[R]", link_field: LinkFieldRef) -> None:
        """
        :param scope: the referencing entity's own `.find(...)`/`.find_one(...)` query to scope
            this search by. Not meant to be constructed directly - obtained via
            `EntityFindMany.search(link_field)`/`EntityFindOne.search(link_field)`.
        :type scope: FindMany[R] | FindOne[R]
        :param link_field: the Link/BackLink field on `scope`'s entity whose target index this
            query searches.
        :type link_field: LinkFieldRef
        """
        # ExpressionField(str).__eq__ builds a query expression (not a bool) against a plain str,
        # which would silently corrupt the dict lookups below - normalize to a genuine str first.
        normalized_link_field = str(link_field)

        # scope.document_model is a real Entity subclass whenever this query is reachable; R binds
        # to the looser BaseModel, so get_link_fields() needs this locally-scoped Entity view.
        scope_model = scope.document_model
        entity_scope_model = cast("type[Entity]", scope_model)
        link_fields = entity_scope_model.get_link_fields()
        if link_fields is None or normalized_link_field not in link_fields:
            raise NotALinkFieldError(entity_scope_model, normalized_link_field)

        target_type = cast("type[T]", link_fields[normalized_link_field].document_class)
        super().__init__(target_type)

        self._scope_model = scope_model
        self._scope_filter = scope.get_filter_query()
        self._scope_limit = 1 if isinstance(scope, FindOne) else None
        self._link_field = normalized_link_field
        self._scope_by_id: dict[Any, R] = {}

    @overload
    def scored(
        self: "ForeignSearchQuery[R, T, R]",
    ) -> "ForeignSearchQuery[R, T, Scored[R]]": ...
    @overload
    def scored(
        self: "ForeignSearchQuery[R, T, Scored[R]]",
    ) -> "ForeignSearchQuery[R, T, Scored[R]]": ...

    def scored(self) -> "ForeignSearchQuery[R, T, Any]":
        """Wraps each result in a `Scored`, carrying its Atlas Search relevance score, once this
        query is run via `to_list()`/`async for`/`paginate()`. Calling it again is a no-op, not
        a double wrap.

        :returns: self, re-typed as `ForeignSearchQuery[R, T, Scored[R]]`.
        :rtype: ForeignSearchQuery[R, T, Any]
        """
        self._with_score = True
        return cast("ForeignSearchQuery[R, T, Any]", self)

    async def _scope_by_id_query(self) -> "dict[Any, R]":
        scope_query: FindMany[Any] = cast("type[Entity]", self._scope_model).find(self._scope_filter)
        if self._scope_limit is not None:
            scope_query = scope_query.limit(self._scope_limit)
        scope_docs = await scope_query.to_list()
        return {getattr(doc, self._link_field).ref.id: cast("R", doc) for doc in scope_docs}

    def __stitch(self, doc: dict[str, Any], scope_by_id: "dict[Any, R]") -> "Any":
        target_id = doc["_id"]  # captured before _parse, which may pop/consume other doc keys
        parsed = self._parse(doc)
        owner = scope_by_id[target_id]
        item = parsed.item if isinstance(parsed, Scored) else parsed
        setattr(owner, self._link_field, item)
        return Scored(item=owner, score=parsed.score) if isinstance(parsed, Scored) else owner

    async def _open_cursor(self) -> "AsyncIterator[dict[str, Any]] | None":
        self._ensure_not_within_transaction()

        self._scope_by_id = await self._scope_by_id_query()
        if not self._scope_by_id:
            return None

        self.filter_in("_id", list(self._scope_by_id))
        pipeline = self.to_pipeline()
        if self._with_score:
            pipeline.append({"$set": {_SCORE_FIELD: {"$meta": "searchScore"}}})

        return self._entity_type.aggregate(pipeline)

    def _parse_doc(self, doc: "dict[str, Any]") -> "Any":
        return self.__stitch(doc, self._scope_by_id)

    async def paginate(self, page: int, limit: int) -> "SearchPage[ItemT]":
        """Runs this query for a single page of matching referencing entities, each with its
        searched Link field populated with its matching target, alongside the total match count
        and any facet buckets configured via `facet(...)`.

        :param page: the 1-indexed page number.
        :type page: int
        :param limit: the page size, and (together with any `.limit()` cap already configured)
            how many top-ranked candidates are actually paginated through.
        :type limit: int
        :returns: a `SearchPage` of `R` (or `Scored[R]`) items, plus
            `facets` when this query has any facet definitions. Empty (zero-bucket facets
            included), without ever issuing a `$search` call, if the scope query currently
            matches nothing.
        :rtype: SearchPage[ItemT]
        :raises SearchWithinTransactionError: if called from within an active `@transactional`
            body - Atlas Search cannot run inside a multi-document transaction.
        """
        self._ensure_not_within_transaction()

        scope_by_id = await self._scope_by_id_query()
        if not scope_by_id:
            return _empty_page(self._facets)

        self.filter_in("_id", list(scope_by_id))

        pipeline = self._build_facet_pipeline(self._build_items_stages(page, limit))

        result = await self._entity_type.aggregate(pipeline).to_list()
        facet = result[0]
        meta = facet["meta"][0] if facet["meta"] else {}

        result_page: SearchPage[Any] = {
            "items": [self.__stitch(doc, scope_by_id) for doc in facet["items"]],
            "total_items": self._extract_total_items(meta),
        }
        if self._facets:
            result_page["facets"] = self._extract_facets(meta)
        return result_page


class _SyncedDeleteMany(_AmbientDeleteMany):
    def __await__(self) -> Generator[Any, None, DeleteResult | None]:
        return _delete_then_sync(self, super().__await__, limit=0)


class _SyncedDeleteOne(_AmbientDeleteOne):
    def __await__(self) -> Generator[Any, None, DeleteResult | None]:
        return _delete_then_sync(self, super().__await__, limit=1)


def _delete_then_sync(
    query: DeleteMany | DeleteOne,
    delete: Callable[[], Generator[Any, None, DeleteResult | None]],
    *,
    limit: int,
) -> Generator[Any, None, DeleteResult | None]:
    from .sync import SyncKind, _deferring, sync_search

    # query.document_model is genuinely an Entity subclass here: this generator only ever runs
    # inside _SyncedDeleteMany/_SyncedDeleteOne, both of which are Entity-scoped.
    meta = _ENTITY_SEARCH_META.get(cast("type[Entity]", query.document_model))
    if _deferring.get() or meta is None or not is_search_enabled() or query.bulk_writer is not None:
        return (yield from delete())

    ids = yield from _matching_ids(query, limit=limit).__await__()
    result = yield from delete()
    yield from sync_search(meta.index, ids, SyncKind.DELETE, session=query.session).__await__()
    return result


async def _matching_ids(query: DeleteMany | DeleteOne, *, limit: int) -> list[PydanticObjectId]:
    collection = query.document_model.get_pymongo_collection()
    cursor = collection.find(query.find_query, projection={"_id": 1}, session=query.session)
    if limit:
        cursor = cursor.limit(limit)

    return [doc["_id"] async for doc in cursor]


class EntityFindMany[FindQueryResultType: BaseModel](_AmbientSessionMixin, FindMany[FindQueryResultType]):
    """`FindMany` specialized for `Entity` subclasses.

    Routes `.find(...).delete()` and `.delete_all()` through write-through search-sync
    verification, and adds `.search(...)` for a further Atlas Search step chained directly off
    `.find(...)`.
    """

    UpdateQueryType = _AmbientUpdateMany
    DeleteQueryType = _SyncedDeleteMany
    AggregationQueryType = _AmbientAggregationQuery

    @overload
    def search(self, link_field: None = None) -> "SearchQuery[FindQueryResultType]": ...
    @overload
    def search(self, link_field: LinkFieldRef) -> "ForeignSearchQuery[FindQueryResultType, Any]": ...

    def search(
        self,
        link_field: "LinkFieldRef | None" = None,
    ) -> "BaseSearchQuery[FindQueryResultType, Any]":
        """Starts a fluent Atlas Search query scoped by this `.find(...)` call's own Mongo
        filter.

        :param link_field: a Link/BackLink field on this call's own entity to search through
            instead. The returned query then searches that field's target index, scoped by this
            call's own filter, returning each owner with its Link field populated with the matching
            target (see `ForeignSearchQuery`). Omit it to search this entity's own index instead,
            scoped by the same filter.
        :type link_field: LinkFieldRef | None
        :returns: a `SearchQuery` bound to this entity's own index (no `link_field`), or a
            `ForeignSearchQuery` bound to the Link target's index (`link_field` given).
        :rtype: BaseSearchQuery[FindQueryResultType, Any]
        :raises NotALinkFieldError: if `link_field` is given but isn't a Link/BackLink field on
            this entity.
        :raises EntityNotSearchableError: if the searched index's own entity (this one, or the
            Link's target) has no `Settings.search_index` configured.
        """
        if link_field is None:
            # self.document_model is Beanie's own DocType typevar, distinct from this class's
            # own FindQueryResultType even though they're always the same real type at runtime.
            document_model = cast("type[FindQueryResultType]", self.document_model)
            return SearchQuery(document_model, scope_filter=self.get_filter_query())
        return ForeignSearchQuery(self, link_field)


class EntityFindOne[FindQueryResultType: BaseModel](_AmbientSessionMixin, FindOne[FindQueryResultType]):
    """`FindOne` specialized for `Entity` subclasses - see `EntityFindMany` for what this adds
    over Beanie's own `FindOne`."""

    UpdateQueryType = _AmbientUpdateOne
    DeleteQueryType = _SyncedDeleteOne
    AggregationQueryType = _AmbientAggregationQuery

    def search(self, link_field: LinkFieldRef) -> "ForeignSearchQuery[FindQueryResultType, Any]":
        """Starts a fluent Atlas Search query against a Link target's index, scoped by this
        `.find_one(...)` call's own filter.

        Unlike `EntityFindMany.search`, `link_field` is required here rather than optional:
        `.find_one(...)` resolves to at most one document, so searching this entity's own index
        (ranking/filtering among many matches) has no meaning once scoped down to one - only
        searching a Link target's index, through that one document's own link, does. Owner
        resolution is capped to at most one document to match `.find_one(...)`'s own semantics
        (see `ForeignSearchQuery`).

        :param link_field: a Link/BackLink field on this call's own entity to search through.
            The returned query searches that field's target index, scoped by this call's own
            filter, returning the owner with its Link field populated with the matching target (see
            `ForeignSearchQuery`).
        :type link_field: LinkFieldRef
        :returns: a `ForeignSearchQuery` bound to the Link target's index.
        :rtype: ForeignSearchQuery[FindQueryResultType, Any]
        :raises NotALinkFieldError: if `link_field` isn't a Link/BackLink field on this entity.
        :raises EntityNotSearchableError: if the Link's target type has no `Settings.search_index`
            configured.
        """
        return ForeignSearchQuery(self, link_field)
