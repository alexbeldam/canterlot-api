import asyncio
import json
import math

from canterlot.dto.book import BookDetails, BookResponse, BookSearchResult, PaginatedBooksResponse
from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError, BookSearchCriteriaMissingError
from canterlot.models.book import BookExternalId, BookProviderIdentifier, SearchParams, TitleStr, split_isbn
from canterlot.models.enums import BookProviderName
from canterlot.providers import BookProvider, ProviderSearchResponse
from canterlot.repositories import BookRepository, CacheRepository
from canterlot.utils import (
    LANGUAGE_MATCH_SUBSCORES,
    best_language_match,
    get_logger,
    redistribute_weights,
    similarity_ratio,
)
from canterlot.utils.format import ISBNStr, LanguageStr

logger = get_logger(__name__)


class BookService:
    MAX_PROVIDER_CHUNK = 40
    RELEVANCE_WEIGHT = 0.85
    COMPLETENESS_WEIGHT = 0.15
    TITLE_WEIGHT = 0.5
    AUTHOR_WEIGHT = 0.3
    LANGUAGE_WEIGHT = 0.2

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

        return PaginatedBooksResponse(
            items=paginated_books, total_items=total_results, current_page=page, page_size=limit
        )

    async def search_external_books(
        self,
        title: TitleStr | None,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
        page: int,
        limit: int,
    ) -> PaginatedBooksResponse:
        log = logger.bind(search_title=title, search_author=author, search_isbn=isbn, page=page, limit=limit)

        if not title and not author and not isbn:
            log.warn("Search rejected: no search criteria provided")
            raise BookSearchCriteriaMissingError("At least one of title, author, or isbn must be provided.")

        provider_chunk_page = math.ceil((page * limit) / self.MAX_PROVIDER_CHUNK)
        start_index = (provider_chunk_page - 1) * self.MAX_PROVIDER_CHUNK
        cache_key = self.__build_cache_key(title, author, isbn, preferred_languages, provider_chunk_page)

        log = log.bind(chunk_page=provider_chunk_page)
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
            return PaginatedBooksResponse(items=[], total_items=0, current_page=page, page_size=limit)

        log.info("Sorting and heuristic scoring aggregated search records", items_to_score=len(raw_books))
        sorted_books = self.__score_and_sort_books(raw_books, title, author, isbn, preferred_languages)

        await self.__cache_results(cache_key, sorted_books, total_results, log)

        return self.__slice_pagination(sorted_books, total_results, page, limit)

    def __build_cache_key(
        self,
        title: TitleStr | None,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
        provider_chunk_page: int,
    ) -> str:
        langs_key = "-".join(sorted(preferred_languages))
        return (
            f"cache:search:{(title or '').lower()}:auth:{author or ''}:"
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
                    book.id.provider = current_provider_name
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
        title: TitleStr | None,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
    ) -> list[BookSearchResult]:
        scored_books = [(self.__score_book(book, title, author, isbn, preferred_languages), book) for book in raw_books]

        scored_books.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_books]

    def __score_book(
        self,
        book: BookSearchResult,
        title: TitleStr | None,
        author: str | None,
        isbn: ISBNStr | None,
        preferred_languages: list[LanguageStr],
    ) -> float:
        if isbn is not None and isbn in (book.isbn_10, book.isbn_13):
            relevance_score = self.RELEVANCE_WEIGHT
        else:
            relevance_score = self.RELEVANCE_WEIGHT * self.__relevance_score(book, title, author, preferred_languages)

        completeness_score = self.COMPLETENESS_WEIGHT * self.__completeness_score(book)

        return relevance_score + completeness_score

    def __relevance_score(
        self,
        book: BookSearchResult,
        title: TitleStr | None,
        author: str | None,
        preferred_languages: list[LanguageStr],
    ) -> float:
        title_score = 0.0
        weights: dict[str, float] = {}
        if title:
            title_score = similarity_ratio(title, book.title)
            weights["title"] = self.TITLE_WEIGHT

        author_score = 0.0
        if author:
            author_score = max((similarity_ratio(author, ret_a) for ret_a in book.authors), default=0)
            weights["author"] = self.AUTHOR_WEIGHT

        language_score = 0.0
        if preferred_languages:
            match_level = best_language_match(book.languages, preferred_languages)
            language_score = LANGUAGE_MATCH_SUBSCORES[match_level]
            weights["language"] = self.LANGUAGE_WEIGHT

        weights = redistribute_weights(weights)

        return (
            title_score * weights.get("title", 0)
            + author_score * weights.get("author", 0)
            + language_score * weights.get("language", 0)
        )

    def __completeness_score(self, book: BookSearchResult) -> float:
        checks = [
            book.cover_url is not None,
            book.year is not None,
            bool(book.authors),
            bool(book.isbn_10 or book.isbn_13),
        ]
        return sum(checks) / len(checks)

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

    async def get_by_identifier(self, identifier: BookExternalId | ISBNStr) -> BookResponse:
        log = logger.bind(identifier=str(identifier))
        log.info("Fetching persistent book record by public identifier")

        if isinstance(identifier, BookProviderIdentifier):
            book = await self.__repo.find_by_external_id(identifier)
        else:
            isbn_10, isbn_13 = split_isbn(identifier)
            book = await self.__repo.find_by_isbn(isbn_10, isbn_13)

        if book is None:
            log.warn("Query mismatch: requested book identifier not found")
            raise BookNotFoundError(f"Book with identifier '{identifier}' not found")

        log.info("Global book reference successfully mapped and returned")
        return BookResponse.model_validate(book, from_attributes=True)
