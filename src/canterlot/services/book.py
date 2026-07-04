import asyncio
import json
import math

from beanie import PydanticObjectId

from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError
from canterlot.models import BookDetails, BookModel, BookSearchResult, PaginatedBooksResponse
from canterlot.models.book import SearchParams, TitleStr
from canterlot.models.enums import BookProviderName
from canterlot.providers import BookProvider, ProviderSearchResponse
from canterlot.repositories import BookRepository, CacheRepository
from canterlot.utils import get_logger, similarity_ratio
from canterlot.utils.format import ISBNStr, LanguageStr

logger = get_logger(__name__)


class BookService:
    MAX_PROVIDER_CHUNK = 40

    def __init__(
        self,
        cache: CacheRepository,
        book_repo: BookRepository,
        providers: list[BookProvider],
    ):
        self.__cache = cache
        self.__repo = book_repo
        self.__providers: dict[BookProviderName, BookProvider] = {p.name: p for p in providers}

    def __slice_pagination(
        self,
        sorted_books: list[BookSearchResult],
        total_results: int,
        page: int,
        limit: int,
    ) -> PaginatedBooksResponse:
        start_idx = ((page - 1) * limit) % self.MAX_PROVIDER_CHUNK
        end_idx = start_idx + limit

        paginated_books = sorted_books[start_idx:end_idx]
        total_pages = math.ceil(total_results / limit)

        return PaginatedBooksResponse(
            books=paginated_books, total_pages=total_pages, current_page=page, total_results=total_results
        )

    async def search_external_books(
        self,
        title: TitleStr,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
        page: int,
        limit: int,
    ) -> PaginatedBooksResponse:
        provider_chunk_page = math.ceil((page * limit) / self.MAX_PROVIDER_CHUNK)
        start_index = (provider_chunk_page - 1) * self.MAX_PROVIDER_CHUNK
        cache_key = self.__build_cache_key(title, author, isbn, preferred_languages, provider_chunk_page)

        log = logger.bind(
            search_title=title,
            search_author=author,
            search_isbn=isbn,
            page=page,
            limit=limit,
            chunk_page=provider_chunk_page,
        )
        log.info("Initiating external books catalog search request")

        cached_response = await self.__try_cache_hit(cache_key, page, limit, log)
        if cached_response is not None:
            return cached_response

        log.info("Cache miss: dispatching parallel upstream volumes query requests")
        search_params = SearchParams(
            title=title,
            authors=[author] if author else [],
            isbn=isbn,
            languages=preferred_languages,
        )

        tasks = [
            provider.fetch_volumes(search_params, start_index, self.MAX_PROVIDER_CHUNK)
            for provider in self.__providers.values()
        ]
        provider_results = await asyncio.gather(*tasks, return_exceptions=True)

        raw_books, total_results = self.__aggregate_provider_results(provider_results, log)

        if not raw_books:
            log.info("Aggregated volume queries returned zero hits across all active providers")
            return PaginatedBooksResponse(books=[], total_pages=0, current_page=page, total_results=0)

        log.info("Sorting and heuristic scoring aggregated search records", items_to_score=len(raw_books))
        sorted_books = self.__score_and_sort_books(raw_books, title, author, preferred_languages)

        await self.__cache_results(cache_key, sorted_books, total_results, log)

        return self.__slice_pagination(sorted_books, total_results, page, limit)

    def __build_cache_key(
        self,
        title: TitleStr,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
        provider_chunk_page: int,
    ) -> str:
        langs_key = "-".join(sorted(preferred_languages))
        return (
            f"cache:search:{title.lower()}:auth:{author or ''}:"
            f"isbn:{isbn or ''}:langs:{langs_key}:chunk_p:{provider_chunk_page}"
        )

    async def __try_cache_hit(self, cache_key: str, page: int, limit: int, log) -> PaginatedBooksResponse | None:
        cached = await self.__cache.find(cache_key)
        if not cached:
            return None

        try:
            payload = json.loads(cached)
            cached_books = [BookSearchResult.model_validate(b) for b in payload["books"]]
            total_results = payload["total_results"]
        except (json.JSONDecodeError, ValueError, KeyError):
            log.warn("Discarding corrupt or outdated cache entry, falling back to a live fetch")
            return None

        log.info("External search satisfied via cache hit")
        return self.__slice_pagination(cached_books, total_results, page, limit)

    async def __cache_results(
        self,
        cache_key: str,
        sorted_books: list[BookSearchResult],
        total_results: int,
        log,
    ) -> None:
        cache_payload = {"books": [b.model_dump(mode="json") for b in sorted_books], "total_results": total_results}
        await self.__cache.save(cache_key, json.dumps(cache_payload), expire_seconds=300)
        log.info("Staged search results dataset in transient cache layers", total_results=total_results)

    def __aggregate_provider_results(
        self,
        provider_results: list[ProviderSearchResponse | BaseException],
        log,
    ) -> tuple[list[BookSearchResult], int]:
        raw_books: list[BookSearchResult] = []
        total_results = 0
        provider_names = list(self.__providers.keys())

        for idx, provider_data in enumerate(provider_results):
            current_provider_name = provider_names[idx]

            if isinstance(provider_data, Exception):
                log.error(
                    "Upstream link provider task failed to respond",
                    provider_name=current_provider_name,
                    error_message=str(provider_data),
                    exc_info=True,
                )
                continue

            if not isinstance(provider_data, dict):
                log.debug("Provider returned invalid payload structure", provider_name=current_provider_name)
                continue

            provider_total = provider_data.get("total_results", 0)
            total_results += provider_total
            books_list = provider_data.get("books", [])

            log.debug(
                "Collected volumes dataset from engine",
                provider_name=current_provider_name,
                count=len(books_list),
                provider_total_results=provider_total,
            )

            for book in books_list:
                if isinstance(book, BookSearchResult):
                    book.provider = current_provider_name
                    raw_books.append(book)
                elif isinstance(book, dict):
                    book["provider"] = current_provider_name
                    try:
                        raw_books.append(BookSearchResult.model_validate(book))
                    except ValueError:
                        log.debug("Skipping malformed book payload from provider", provider_name=current_provider_name)

        return raw_books, total_results

    def __score_and_sort_books(
        self,
        raw_books: list[BookSearchResult],
        title: TitleStr,
        author: str | None,
        preferred_languages: list[LanguageStr],
    ) -> list[BookSearchResult]:
        scored_books = []
        for book in raw_books:
            score = similarity_ratio(title, book.title) * 100
            if author:
                greatest_sim_author = max([similarity_ratio(author, ret_a) for ret_a in book.authors] or [0])
                score += greatest_sim_author * 70

            for lang in preferred_languages:
                if lang in book.languages:
                    score += 50
                    break

            scored_books.append((score, book))

        scored_books.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_books]

    async def get_external_book_details(self, provider_book_id: str, provider: BookProviderName) -> BookDetails:
        log = logger.bind(external_book_id=provider_book_id, provider_name=provider)
        log.info("Fetching volume details card from external provider engine")

        provider_engine = self.__providers.get(provider)
        if not provider_engine:
            log.warn("Query aborted: provider engine key does not exist")
            raise BookDetailsNotFoundError(f"No active provider engine found matching '{provider}'")

        details = await provider_engine.fetch_volume_details(provider_book_id)
        if not details:
            log.warn("Upstream fetch mismatch: item record missing on external registry")
            raise BookDetailsNotFoundError(f"Book with ID '{provider_book_id}' could not be found via {provider}.")

        log.info("Successfully recovered third-party detailed book context")
        return details

    async def get_by_id(self, book_id: PydanticObjectId) -> BookModel:
        log = logger.bind(book_id=str(book_id))
        log.info("Fetching persistent book record from global database collection")

        book = await self.__repo.find_by_id(book_id)
        if book is None:
            log.warn("Query mismatch: requested book object identifier not found")
            raise BookNotFoundError(f"Book with ID '{book_id}' not found")

        log.info("Global book reference successfully mapped and returned")
        return book
