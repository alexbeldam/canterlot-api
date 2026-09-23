import asyncio
from collections.abc import Mapping
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.operations import SearchIndexModel

from canterlot.models import SEARCH_INDEX_MAP
from canterlot.utils import get_logger

logger = get_logger(__name__)


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

    for attempt in range(1, max_attempts + 1):
        if docs and docs[0].get("queryable"):
            log.info("Search index is queryable.")
            return
        log.warn("Search index not yet queryable, retrying.", attempt=attempt)
        await asyncio.sleep(poll_interval)
        docs = await (await collection.list_search_indexes(name)).to_list()

    log.error("Search index never became queryable.")
    raise RuntimeError(f"Search index {name!r} never became queryable")


async def ensure_registered_search_indexes() -> None:
    for name, spec in SEARCH_INDEX_MAP.items():
        await _ensure_search_index(spec.model.get_pymongo_collection(), name, spec.definition)
