import functools
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any

from beanie import Document
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.operations import SearchIndexModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from canterlot.models import SEARCH_INDEX_MAP
from canterlot.utils import get_logger

logger = get_logger(__name__)


class _NotYetQueryableError(Exception):
    pass


class _NotYetSearchableError(Exception):
    pass


async def _ensure_search_index(
    collection: AsyncCollection[Mapping[str, Any]],
    name: str,
    definition: Mapping[str, Any],
    *,
    max_attempts: int = 30,
    poll_interval: float = 1.0,
) -> None:
    log = logger.bind(index_name=name, collection=collection.name)

    docs = await (await collection.list_search_indexes(name)).to_list()
    if not docs:
        await collection.create_search_index(SearchIndexModel(definition=definition, name=name))
        log.info("Created search index, waiting for it to become queryable.")
        docs = await (await collection.list_search_indexes(name)).to_list()
    else:
        log.info("Search index already exists, checking queryable status.")

    @retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_fixed(poll_interval),
        retry=retry_if_exception_type(_NotYetQueryableError),
        before_sleep=lambda state: log.warn("Search index not yet queryable, retrying.", attempt=state.attempt_number),
        reraise=True,
    )
    async def _poll() -> None:
        nonlocal docs
        if docs and docs[0].get("queryable"):
            return
        docs = await (await collection.list_search_indexes(name)).to_list()
        raise _NotYetQueryableError

    try:
        await _poll()
    except _NotYetQueryableError as exc:
        log.error("Search index never became queryable.")
        raise RuntimeError(f"Search index {name!r} never became queryable") from exc

    log.info("Search index is queryable.")


async def ensure_registered_search_indexes() -> None:
    for name, spec in SEARCH_INDEX_MAP.items():
        await _ensure_search_index(spec.model.get_pymongo_collection(), name, spec.definition)


async def _wait_until_searchable(
    collection: AsyncCollection[Mapping[str, Any]],
    index_name: str,
    doc_id: Any,
    *,
    max_attempts: int = 40,
    poll_interval: float = 0.25,
) -> None:
    # Atlas Search indexes asynchronously off the oplog; poll by _id until the write lands.
    log = logger.bind(index_name=index_name, collection=collection.name, doc_id=str(doc_id))

    @retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_fixed(poll_interval),
        retry=retry_if_exception_type(_NotYetSearchableError),
        before_sleep=lambda state: log.warn("Document not yet searchable, retrying.", attempt=state.attempt_number),
        reraise=True,
    )
    async def _poll() -> None:
        pipeline: list[Mapping[str, Any]] = [
            {"$search": {"index": index_name, "compound": {"filter": [{"equals": {"path": "_id", "value": doc_id}}]}}},
            {"$limit": 1},
            {"$project": {"_id": 1}},
        ]
        docs = await (await collection.aggregate(pipeline)).to_list()
        if not docs:
            raise _NotYetSearchableError

    try:
        await _poll()
    except _NotYetSearchableError as exc:
        log.error("Document never became searchable.")
        raise RuntimeError(f"Document {doc_id!r} never became searchable in index {index_name!r}") from exc

    log.info("Document is searchable.")


def _index_name_for(model: type[Document]) -> str:
    for name, spec in SEARCH_INDEX_MAP.items():
        if spec.model is model:
            return name
    raise NotImplementedError(f"No search index is registered in SEARCH_INDEX_MAP for {model.__name__}.")


def searchable[T: Document, **P](fn: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
    """Waits for a freshly-written Document to become visible to its Atlas Search index."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        doc = await fn(*args, **kwargs)
        index_name = _index_name_for(type(doc))
        await _wait_until_searchable(type(doc).get_pymongo_collection(), index_name, doc.id)
        return doc

    return wrapper
