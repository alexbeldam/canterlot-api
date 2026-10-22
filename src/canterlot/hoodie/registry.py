from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymongo.asynchronous.client_session import AsyncClientSession

from .fields import SearchableField
from .polling import HoodiePollingConfig

if TYPE_CHECKING:
    from .entity import Entity

_ALL_ENTITIES: set[type["Entity"]] = set()
_ENTITY_SEARCH_META: dict[type["Entity"], "SearchMeta"] = {}
_INDEX_TO_ENTITY: dict[str, type["Entity"]] = {}

_CURRENT_SESSION: ContextVar[AsyncClientSession | None] = ContextVar("_CURRENT_SESSION", default=None)

# Runtime switch set by init_hoodie(search=...). A function pair, not a bare module
# attribute, so consumers always read the current value instead of one captured at import time.
_search_enabled: bool = True

# Runtime polling config set by init_hoodie(polling=...), same function-pair rationale as
# _search_enabled above.
_polling_config: HoodiePollingConfig = HoodiePollingConfig()


def set_search_enabled(enabled: bool) -> None:
    global _search_enabled
    _search_enabled = enabled


def is_search_enabled() -> bool:
    return _search_enabled


def set_polling_config(config: HoodiePollingConfig) -> None:
    """Replaces the process-wide polling config used by search-sync and index-build checks.

    `init_hoodie(polling=...)` calls this, so most callers never need to.

    :param config: the polling config to make active.
    :type config: HoodiePollingConfig
    """
    global _polling_config
    _polling_config = config


def get_polling_config() -> HoodiePollingConfig:
    """Returns the polling config currently in effect for the process.

    :returns: the active config (hoodie's defaults until `init_hoodie` or `set_polling_config`
        changes it).
    :rtype: HoodiePollingConfig
    """
    return _polling_config


@dataclass(frozen=True, slots=True)
class SearchMeta:
    index: str
    fields: set[SearchableField]
