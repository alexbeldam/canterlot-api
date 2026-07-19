from typing import Protocol, TypedDict

from canterlot.dto.book import BookDetails, BookSearchResult
from canterlot.models.book import SearchParams
from canterlot.types import BookProviderName


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
