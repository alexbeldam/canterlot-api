import asyncio

from beanie import init_beanie
from pydantic import PydanticUndefinedAnnotation
from pymongo.asynchronous.database import AsyncDatabase

from .exceptions import UnresolvedEntityReferenceError
from .indexes import drop_registered_search_indexes, ensure_registered_search_indexes
from .polling import HoodiePollingConfig
from .registry import _ALL_ENTITIES, is_search_enabled, set_polling_config


def complete_forward_references() -> None:
    """Completes every registered Entity whose string annotations are still unresolved.

    Entities that reference each other through string annotations (a `Link`/`BackLink` to a
    class imported only under `TYPE_CHECKING`, to avoid a circular import) stay incomplete
    until this runs. `init_hoodie` calls it itself; call it directly only when something
    needs the models complete before then, such as a tool that builds on them at import time.
    Safe to call repeatedly: complete entities are skipped.

    Resolves each name against every registered Entity by class name, so every Entity the
    annotations name must already be imported.

    :raises UnresolvedEntityReferenceError: if an Entity's string annotation names a class that
        is not a registered Entity.
    """
    targets = list(_ALL_ENTITIES)
    namespace = {entity.__name__: entity for entity in targets}
    for entity in targets:
        if entity.__pydantic_complete__:
            continue
        try:
            entity.model_rebuild(_types_namespace=namespace)
        except PydanticUndefinedAnnotation as error:
            raise UnresolvedEntityReferenceError(entity, error.name or str(error)) from error


async def init_hoodie(
    database: AsyncDatabase,
    /,
    *,
    polling: HoodiePollingConfig | None = None,
) -> None:
    """Initializes Beanie for every registered Entity subclass and builds/updates each one's
    Atlas Search index.

    Every Entity subclass registers itself at class-definition time, so this must run only
    after every Entity subclass your app defines has actually been imported. One
    still-unimported subclass is simply invisible to Beanie until then.

    Entities with unresolved string annotations are completed first (see
    `complete_forward_references`).

    :param database: the Mongo database to initialize Beanie against.
    :type database: AsyncDatabase
    :param polling: the search-sync/index-build polling intervals to use for the rest of
        the process. Omitted, it preserves whatever config is currently active (hoodie's own
        production-tuned defaults on a process's very first call).
    :type polling: HoodiePollingConfig | None
    :raises UnresolvedEntityReferenceError: if an Entity's string annotation names a class that
        is not a registered Entity.
    :raises SearchIndexNeverQueryableError: if an index never becomes queryable within the
        polling window.
    """
    if polling is not None:
        set_polling_config(polling)
    complete_forward_references()
    await init_beanie(database=database, document_models=list(_ALL_ENTITIES))

    if is_search_enabled():
        await ensure_registered_search_indexes()


async def reset_hoodie(database: AsyncDatabase) -> None:
    """Drops every registered Entity's underlying collection outright, then re-runs
    `init_hoodie` (preserving, as it always does when omitted, the active `polling` config)
    to recreate them and rebuild their search indexes from scratch.

    A full wipe, not a selective cleanup, meant for resetting a local or seeded database.

    :param database: the Mongo database to reinitialize Beanie against.
    :type database: AsyncDatabase
    :raises SearchIndexNeverDroppedError: if search is currently enabled and an index is
        still listed after being dropped, within the polling window.
    :raises SearchIndexNeverQueryableError: if search is currently enabled and a rebuilt
        index never becomes queryable within the polling window.
    """
    # mongot keeps a dropped collection's index under the same name, so a recreated
    # collection would adopt a ghost index that never indexes its documents.
    if is_search_enabled():
        await drop_registered_search_indexes()

    # Each entity owns its own collection, so these drops are independent of each other.
    await asyncio.gather(*(cls.get_pymongo_collection().drop() for cls in _ALL_ENTITIES))

    await init_hoodie(database)
