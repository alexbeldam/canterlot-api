"""Test support for code built on hoodie. Not re-exported from `canterlot.hoodie`.

Context managers are named after what the block does to `<x>`:

- `override_<x>`: the block runs with a replacement for `<x>` and the original is restored on
  exit (`override_registry` is empty, `override_polling_config` takes the config to apply).
  `disable_<x>` is the same with one fixed replacement (`disable_search`).
- `temporary_<x>`: the block starts with the current `<x>` and everything changed inside is
  temporary, undone on exit, so real state stays visible (`temporary_type_resolvers`).
"""

import asyncio
from collections.abc import Generator
from contextlib import contextmanager

from .entity import Entity
from .fields import _TYPE_RESOLVERS
from .polling import HoodiePollingConfig
from .registry import (
    _ALL_ENTITIES,
    _ENTITY_SEARCH_META,
    _INDEX_TO_ENTITY,
    get_polling_config,
    is_search_enabled,
    set_polling_config,
    set_search_enabled,
)


@contextmanager
def disable_search() -> Generator[None]:
    """Turns Atlas Search off for the duration of the block.

    Meant for test setups against a Mongo without Atlas Search support (such as an in-memory
    mock). While active, `init_hoodie` skips search index management and `@synced` writes skip
    write-through verification. The previous setting is restored on exit, including when the
    block raises.

    :returns: a context manager that yields nothing.
    :rtype: Generator[None]
    """
    previous = is_search_enabled()
    set_search_enabled(False)
    try:
        yield
    finally:
        set_search_enabled(previous)


@contextmanager
def override_registry() -> Generator[None]:
    """Runs the block against an empty Entity registry.

    Inside the block no previously defined Entity is registered, so its class names, search
    index names and forward references cannot collide with, or resolve to, the real ones.
    Entity subclasses defined inside the block register as usual, so `init_hoodie` sees
    only them. On exit, including when the block raises, the registry is restored to what it
    was on entry. Meant for tests that define a deliberately broken or throwaway Entity.

    Real Entities are invisible inside the block: they cannot be the target of a forward
    reference, and their writes skip search-sync verification.

    :returns: a context manager that yields nothing.
    :rtype: Generator[None]
    """
    entities = set(_ALL_ENTITIES)
    search_meta = dict(_ENTITY_SEARCH_META)
    index_owners = dict(_INDEX_TO_ENTITY)
    _ALL_ENTITIES.clear()
    _ENTITY_SEARCH_META.clear()
    _INDEX_TO_ENTITY.clear()
    try:
        yield
    finally:
        # Restored in place: other modules hold references to these same containers.
        _ALL_ENTITIES.clear()
        _ALL_ENTITIES.update(entities)
        _ENTITY_SEARCH_META.clear()
        _ENTITY_SEARCH_META.update(search_meta)
        _INDEX_TO_ENTITY.clear()
        _INDEX_TO_ENTITY.update(index_owners)


@contextmanager
def override_polling_config(config: HoodiePollingConfig) -> Generator[None]:
    """Applies a polling config for the duration of the block.

    The previously active config is restored on exit, including when the block raises.

    :param config: the polling config to make active inside the block.
    :type config: HoodiePollingConfig
    :returns: a context manager that yields nothing.
    :rtype: Generator[None]
    """
    previous = get_polling_config()
    set_polling_config(config)
    try:
        yield
    finally:
        set_polling_config(previous)


@contextmanager
def temporary_type_resolvers() -> Generator[None]:
    """Undoes every type resolver registered inside the block when it exits.

    Resolvers registered before the block stay in effect inside it. The previous resolver
    list, in its previous order, is restored on exit, including when the block raises. Atlas
    mapping strategies are not covered.

    :returns: a context manager that yields nothing.
    :rtype: Generator[None]
    """
    resolvers = list(_TYPE_RESOLVERS)
    try:
        yield
    finally:
        # Restored in place: fields.py iterates this same list object.
        _TYPE_RESOLVERS.clear()
        _TYPE_RESOLVERS.extend(resolvers)


def registered_entities() -> frozenset[type[Entity]]:
    """Returns the Entity subclasses currently registered for `init_hoodie`.

    A snapshot: later registrations do not change the returned set. Abstract roots
    (`Settings.is_root = True`) and classes whose definition raised are not registered.

    :returns: every Entity subclass `init_hoodie` would initialize.
    :rtype: frozenset[type[Entity]]
    """
    return frozenset(_ALL_ENTITIES)


async def delete_all_entities() -> None:
    """Deletes every document from every registered Entity's collection, leaving the
    collections (and their search indexes) themselves in place.

    Meant for resetting state between test cases, not for application code. It has no
    guard against running against a production database.
    """
    # Each entity owns its own collection, so these deletes are independent of each other.
    await asyncio.gather(*(cls.delete_all() for cls in _ALL_ENTITIES))
