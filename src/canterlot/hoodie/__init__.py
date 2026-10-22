"""A Beanie/MongoDB ODM extension layer.

Provides four integrated pieces on top of `beanie.Document`:

- `Entity` / `searchable`: subclass `Entity` and mark fields with `searchable(...)` to get an
  automatically managed Atlas Search index, built and kept in sync by `init_hoodie`.
- `Entity.search()` / `SearchQuery`: a fluent Atlas Search query builder bound to an Entity's
  own index (`text`/`filter_in`/`filter_equals`/`filter_not_equals`/`phrase`/`should`/`facet`/
  `project`/`scored`/`limit` clauses, run with `to_list()`, `async for`, or `paginate()`).
  `SomeEntity.find(match).search(...)` extends this further: with a Link field, `ForeignSearchQuery`
  searches the Link target's own index instead, scoped by `match`, returning each owner with its
  Link field populated with the matching target; with no field, it returns a `SearchQuery`
  pre-scoped by `match` itself, for a Mongo filter Atlas's own clauses can't express directly.
- `synced` (and, transitively, `Entity`'s own insert/save/replace/update/insert_many): every
  successful write is verified against the entity's search index before the call returns.
- `transactional`: runs a method/function body inside a single real Mongo multi-document
  transaction, batching every write's search-sync verification into one wait at commit time.

Call `init_hoodie(database)` once at startup, after every `Entity` subclass has been
imported, to register them with Beanie and build/update their search indexes. Pass
`polling=HoodiePollingConfig(...)` to tune the search-sync/index-build polling intervals
away from their production-tuned defaults (e.g. against a faster local search process).
"""

from .database import DatabaseManager
from .entity import Entity
from .exceptions import DatabaseManagerNotOpenError, TransactionError
from .fields import searchable
from .lifecycle import delete_all_entities, init_hoodie, reset_hoodie
from .polling import HoodiePollingConfig, PollingPolicy
from .query import (
    BaseSearchQuery,
    EntityFindMany,
    EntityFindOne,
    FacetBucket,
    ForeignSearchQuery,
    Scored,
    SearchPage,
    SearchQuery,
)
from .registry import get_polling_config, set_polling_config
from .sync import SyncKind, deferred_search_sync, sync_search, synced
from .transactions import transactional

__all__ = [
    "BaseSearchQuery",
    "DatabaseManager",
    "DatabaseManagerNotOpenError",
    "Entity",
    "EntityFindMany",
    "EntityFindOne",
    "FacetBucket",
    "ForeignSearchQuery",
    "HoodiePollingConfig",
    "PollingPolicy",
    "Scored",
    "SearchPage",
    "SearchQuery",
    "SyncKind",
    "TransactionError",
    "deferred_search_sync",
    "delete_all_entities",
    "get_polling_config",
    "init_hoodie",
    "reset_hoodie",
    "searchable",
    "set_polling_config",
    "sync_search",
    "synced",
    "transactional",
]
