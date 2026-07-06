from typing import Protocol, TypedDict

from canterlot.dto.book import BookDetails, BookSearchResult
from canterlot.models import LinkCandidate
from canterlot.models.book import SearchParams
from canterlot.models.enums import BookProviderName, LinkProviderName


class LinkProvider(Protocol):
    @property
    def name(self) -> LinkProviderName: ...

    async def find_links(self, params: SearchParams) -> list[LinkCandidate]: ...


class ProviderSearchResponse(TypedDict):
    books: list[BookSearchResult]
    total_results: int


class BookProvider(Protocol):
    @property
    def name(self) -> BookProviderName: ...

    async def fetch_volumes(
        self,
        params: SearchParams,
        start_index: int,
        max_results: int,
    ) -> ProviderSearchResponse: ...
    async def fetch_volume_details(self, provider_book_id: str) -> BookDetails | None: ...
