import asyncio
import contextlib
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import structlog
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import CollectionInvalid
from pymongo.operations import SearchIndexModel

from .exceptions import SearchIndexNeverDroppedError, SearchIndexNeverQueryableError
from .fields import SearchableField
from .polling import PollCoalescer, poll_until
from .registry import _ENTITY_SEARCH_META, SearchMeta, get_polling_config

if TYPE_CHECKING:
    from .entity import Entity

logger = structlog.get_logger(__name__)

# Every registered entity's index build fires at once otherwise, competing for the same
# Atlas Search (mongot) process - bounding concurrency avoids that contention.
_INDEX_BUILD_CONCURRENCY = 4

# Coalesces concurrent calls for the *same* index (e.g. two overlapping init_hoodie()
# calls) into one create/update-and-poll cycle instead of racing independent API calls.
_index_coalescer: PollCoalescer[str, None] = PollCoalescer()


def _build_atlas_index_definition(fields: set[SearchableField]) -> dict[str, Any]:
    field_mappings: dict[str, Any] = {}
    for field in fields:
        _insert_field_mapping(field_mappings, field.path.split("."), field.to_atlas_mapping())

    return {
        "mappings": {
            "dynamic": False,
            "fields": field_mappings,
        }
    }


def _insert_field_mapping(
    fields: dict[str, Any],
    path_parts: list[str],
    mapping: dict[str, Any] | list[dict[str, Any]],
) -> None:
    head, *rest = path_parts
    if not rest:
        fields[head] = mapping
        return

    node = fields.setdefault(head, {"type": "document", "fields": {}})
    _insert_field_mapping(node["fields"], rest, mapping)


def _compute_schema_hash(fields: set[SearchableField]) -> str:
    fingerprints = sorted(
        (f.fingerprint_dict() for f in fields),
        key=lambda d: d["path"],
    )
    serialized = json.dumps(fingerprints, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


async def ensure_registered_search_indexes() -> None:
    semaphore = asyncio.Semaphore(_INDEX_BUILD_CONCURRENCY)

    async def _bounded(cls: "type[Entity]", meta: SearchMeta) -> None:
        async with semaphore:
            await _ensure_search_index(collection=cls.get_pymongo_collection(), name=meta.index, fields=meta.fields)

    await asyncio.gather(*(_bounded(cls, meta) for cls, meta in _ENTITY_SEARCH_META.items()))


async def drop_registered_search_indexes() -> None:
    await asyncio.gather(
        *(_drop_search_index(cls.get_pymongo_collection(), meta.index) for cls, meta in _ENTITY_SEARCH_META.items())
    )


async def _drop_search_index(collection: AsyncCollection[Mapping[str, Any]], name: str) -> None:
    log = logger.bind(index_name=name, collection=collection.name)

    async def listed() -> bool:
        return bool(await (await collection.list_search_indexes(name)).to_list())

    if not await listed():
        return

    log.info("Dropping search index.")
    await collection.drop_search_index(name)

    async def gone() -> bool:
        return not await listed()

    def on_retry(attempt: int) -> None:
        log.debug("Search index still listed after drop, retrying.", attempt=attempt)

    if not await poll_until(gone, policy=get_polling_config().index_build, on_retry=on_retry):  # pragma: no cover
        log.error("Search index never dropped.")  # only reachable with a broken Atlas deployment
        raise SearchIndexNeverDroppedError(name)


async def _ensure_search_index(
    collection: AsyncCollection[Mapping[str, Any]],
    name: str,
    fields: set[SearchableField],
) -> None:
    await _index_coalescer.run(name, lambda: _do_ensure_search_index(collection, name, fields))


async def _do_ensure_search_index(
    collection: AsyncCollection[Mapping[str, Any]],
    name: str,
    fields: set[SearchableField],
) -> None:
    log = logger.bind(index_name=name, collection=collection.name)

    await _ensure_collection_exists(collection)

    target_definition = _build_atlas_index_definition(fields)
    target_hash = _compute_schema_hash(fields)

    existing_indexes = await (await collection.list_search_indexes(name)).to_list()

    if existing_indexes:
        existing = existing_indexes[0]
        current_definition = existing.get("latestDefinition") or existing.get("definition", {})

        if _has_schema_drifted(current_definition, target_definition):
            log.info(
                "Search index schema drift detected. Updating search index definition.",
                schema_hash=target_hash,
            )
            await collection.update_search_index(name, target_definition)
        else:
            log.info("Search index is up-to-date.", schema_hash=target_hash)
    else:
        log.info("Creating explicit static search index.", schema_hash=target_hash)
        await collection.create_search_index(SearchIndexModel(definition=target_definition, name=name))

    async def queryable() -> bool:
        docs = await (await collection.list_search_indexes(name)).to_list()
        if not docs:
            return False

        idx = docs[0]
        is_queryable = bool(idx.get("queryable"))
        status = idx.get("status")
        return is_queryable and status not in ("BUILDING", "UPDATING")

    def on_retry(attempt: int) -> None:
        log.debug("Search index update/build not yet queryable, retrying.", attempt=attempt)

    if not await poll_until(queryable, policy=get_polling_config().index_build, on_retry=on_retry):  # pragma: no cover
        log.error("Search index never became queryable.")  # only reachable with a broken Atlas deployment
        raise SearchIndexNeverQueryableError(name)

    log.info("Search index is ready and queryable.", schema_hash=target_hash)


# Atlas injects these into every echoed-back mapping (string fields get indexOptions/norms/
# store; nested "document" fields get their own dynamic) even though we never set them.
_SERVER_INJECTED_MAPPING_KEYS = frozenset({"indexOptions", "norms", "store", "dynamic"})


def _strip_server_defaults(node: Any) -> Any:
    if isinstance(node, list):
        return [_strip_server_defaults(item) for item in node]

    if not isinstance(node, dict):
        return node

    stripped = {key: _strip_server_defaults(value) for key, value in node.items()}
    if "type" in stripped:
        for key in _SERVER_INJECTED_MAPPING_KEYS:
            stripped.pop(key, None)
    return stripped


def _has_schema_drifted(current_def: dict[str, Any], target_def: dict[str, Any]) -> bool:

    def normalize(d: dict[str, Any]) -> str:
        return json.dumps(_strip_server_defaults(d), sort_keys=True)

    return normalize(current_def) != normalize(target_def)


async def _ensure_collection_exists(collection: AsyncCollection[Mapping[str, Any]]) -> None:
    with contextlib.suppress(CollectionInvalid):
        await collection.database.create_collection(collection.name)
