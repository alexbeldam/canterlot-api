import asyncio

from beanie import init_beanie
from pymongo.asynchronous.database import AsyncDatabase

from .indexes import drop_registered_search_indexes, ensure_registered_search_indexes
from .polling import HoodiePollingConfig
from .registry import _ALL_ENTITIES, is_search_enabled, set_polling_config, set_search_enabled


async def init_hoodie(
    database: AsyncDatabase,
    /,
    *,
    search: bool = True,
    polling: HoodiePollingConfig | None = None,
) -> None:
    """Initializes Beanie for every registered Entity subclass and, unless disabled,
    builds/updates each one's Atlas Search index.

    Every Entity subclass registers itself at class-definition time, so this must run only
    after every Entity subclass your app defines has actually been imported. One
    still-unimported subclass is simply invisible to Beanie until then.

    `search=False` skips both search index management here and `@synced`'s write-through
    verification for the rest of the process (until re-enabled by another `init_hoodie`
    call). Use this against a Mongo deployment with no Atlas Search support.

    :param database: the Mongo database to initialize Beanie against.
    :type database: AsyncDatabase
    :param search: when False, skips search index management and write-through
        verification for the rest of the process.
    :type search: bool
    :param polling: the search-sync/index-build polling intervals to use for the rest of
        the process. Omitted, it preserves whatever config is currently active (hoodie's own
        production-tuned defaults on a process's very first call).
    :type polling: HoodiePollingConfig | None
    :raises SearchIndexNeverQueryableError: if `search` is True and an index never becomes
        queryable within the polling window.
    """
    set_search_enabled(search)
    if polling is not None:
        set_polling_config(polling)
    await init_beanie(database=database, document_models=list(_ALL_ENTITIES))

    if search:
        await ensure_registered_search_indexes()


async def delete_all_entities() -> None:
    """Deletes every document from every registered Entity's collection, leaving the
    collections (and their search indexes) themselves in place.

    Meant for resetting state between test cases, not for application code. It has no
    guard against running against a production database.
    """
    # Each entity owns its own collection, so these deletes are independent of each other.
    await asyncio.gather(*(cls.delete_all() for cls in _ALL_ENTITIES))


async def reset_hoodie(database: AsyncDatabase) -> None:
    """Drops every registered Entity's underlying collection outright, then re-runs
    `init_hoodie` (preserving whichever `search` setting - and, as `init_hoodie` always
    does when omitted, `polling` config - are currently active) to recreate them and
    rebuild their search indexes from scratch.

    A full wipe, not a selective cleanup, meant for resetting a test database between test
    sessions.

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

    # Preserves whatever search setting is currently active rather than silently re-enabling
    # it; polling is preserved automatically by init_hoodie's own default.
    await init_hoodie(database, search=is_search_enabled())
