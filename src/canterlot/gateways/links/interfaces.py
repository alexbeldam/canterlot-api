from typing import Protocol

from canterlot.models.book import LinkCandidate, SearchParams
from canterlot.types import LinkProviderName


class LinkProvider(Protocol):
    @property
    def name(self) -> LinkProviderName: ...

    async def find_links(self, params: SearchParams) -> list[LinkCandidate]: ...
