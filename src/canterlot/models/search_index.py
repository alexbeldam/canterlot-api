from collections.abc import Mapping
from typing import Any, NamedTuple

from beanie import Document


class SearchIndexSpec(NamedTuple):
    model: type[Document]
    definition: Mapping[str, Any]
