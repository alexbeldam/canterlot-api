import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import (
    BookDetailsNotFoundError,
    BookNotFoundError,
    BookSearchCriteriaMissingError,
    GatewayConfigurationError,
)
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.read_book import RatingStats
from canterlot.repositories import ReadBookRepository
from canterlot.services.book import BookService
from canterlot.types import BookProviderName
from tools.factories import BookDetailsFactory, BookFactory, BookSearchResultFactory


def _service(
    cache_repo: AsyncMock,
    book_repo: AsyncMock,
    book_provider: AsyncMock,
    read_book_repo: AsyncMock | None = None,
) -> BookService:
    return BookService(cache_repo, book_repo, read_book_repo or AsyncMock(spec=ReadBookRepository), [book_provider])


def describe_search_external_books_validation():
    async def it_raises_when_title_author_and_isbn_are_all_missing(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookSearchCriteriaMissingError):
            await service.search_external_books(
                title=None,
                author=None,
                isbn=None,
                preferred_languages=[],
                page=1,
                limit=10,
            )

        book_provider.fetch_volumes.assert_not_called()

    async def it_does_not_crash_building_the_cache_key_when_title_is_none(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = {"books": [BookSearchResultFactory.build()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title=None,
            author=None,
            isbn="0261102214",
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1

    async def it_ranks_by_author_alone_when_title_is_not_given(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        matching_author = BookSearchResultFactory.build(authors=["J.R.R. Tolkien"])
        other_author = BookSearchResultFactory.build(authors=["Another Author"])
        book_provider.fetch_volumes.return_value = {"books": [other_author, matching_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title=None,
            author="J.R.R. Tolkien",
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items[0].id == matching_author.id


def describe_search_external_books_cache_behavior():
    async def it_returns_cached_results_without_contacting_providers(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cached_book = BookSearchResultFactory.build().model_dump(mode="json")
        cache_repo.find.return_value = {"total_results": 1, "books": json.dumps([cached_book])}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1
        assert result.total_items == 1
        book_provider.fetch_volumes.assert_not_called()

    async def it_falls_back_to_a_live_fetch_when_the_cache_entry_is_corrupt(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = "not valid json"
        book_provider.fetch_volumes.return_value = {"books": [BookSearchResultFactory.build()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1
        book_provider.fetch_volumes.assert_awaited_once()

    async def it_falls_back_to_a_live_fetch_when_the_cache_entry_is_missing_expected_keys(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cached_book = BookSearchResultFactory.build().model_dump(mode="json")
        cache_repo.find.return_value = {"books": json.dumps([cached_book])}
        book_provider.fetch_volumes.return_value = {"books": [BookSearchResultFactory.build()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1
        book_provider.fetch_volumes.assert_awaited_once()

    async def it_saves_a_json_serializable_payload_to_the_cache_on_a_miss(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = {"books": [BookSearchResultFactory.build()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        cache_repo.save.assert_awaited_once()
        cached_map = cache_repo.save.call_args.args[1]
        assert cached_map["total_results"] == 1


def describe_search_external_books_provider_aggregation():
    async def it_skips_a_provider_that_raises(cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.side_effect = RuntimeError("upstream is down")
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items == []
        assert result.total_pages == 0

    async def it_skips_a_provider_returning_an_unexpected_payload_shape(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = "not-a-dict"
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items == []

    async def it_skips_a_malformed_book_payload_but_keeps_the_valid_ones(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        malformed = {"id": "google-books__bad"}
        book_provider.fetch_volumes.return_value = {
            "books": [malformed, BookSearchResultFactory.build()],
            "total_results": 2,
        }
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1

    async def it_leaves_the_cover_url_unset_when_no_provider_supplied_one(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        no_cover = BookSearchResultFactory.build(cover_url=None)
        book_provider.fetch_volumes.return_value = {"books": [no_cover], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1
        assert result.items[0].cover_url is None

    async def it_accepts_a_provider_returning_an_already_built_book_search_result(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        prebuilt = BookSearchResultFactory.build()
        book_provider.fetch_volumes.return_value = {"books": [prebuilt], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert len(result.items) == 1
        assert result.items[0].id.provider == BookProviderName.GOOGLE


def describe_search_external_books_scoring():
    async def it_ranks_the_closest_title_match_first(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        close_match = BookSearchResultFactory.build(title="The Hobbit")
        far_match = BookSearchResultFactory.build(title="Completely Unrelated Book")
        book_provider.fetch_volumes.return_value = {"books": [far_match, close_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert [b.id for b in result.items] == [close_match.id, far_match.id]

    async def it_boosts_books_matching_a_preferred_language(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        english = BookSearchResultFactory.build(title="A Tale", languages=["en"])
        spanish = BookSearchResultFactory.build(title="A Tale", languages=["es"])
        book_provider.fetch_volumes.return_value = {"books": [spanish, english], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author=None,
            isbn=None,
            preferred_languages=["en"],
            page=1,
            limit=10,
        )

        assert result.items[0].id == english.id

    async def it_ranks_an_exact_language_match_above_a_same_base_language_match(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        exact = BookSearchResultFactory.build(title="A Tale", languages=["pt-BR"])
        base_only = BookSearchResultFactory.build(title="A Tale", languages=["pt-PT"])
        book_provider.fetch_volumes.return_value = {"books": [base_only, exact], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author=None,
            isbn=None,
            preferred_languages=["pt-BR"],
            page=1,
            limit=10,
        )

        assert [b.id for b in result.items] == [exact.id, base_only.id]

    async def it_boosts_a_same_base_language_match_above_no_language_match(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        base_only = BookSearchResultFactory.build(title="A Tale", languages=["pt-PT"])
        no_match = BookSearchResultFactory.build(title="A Tale", languages=["es"])
        book_provider.fetch_volumes.return_value = {"books": [no_match, base_only], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author=None,
            isbn=None,
            preferred_languages=["pt-BR"],
            page=1,
            limit=10,
        )

        assert [b.id for b in result.items] == [base_only.id, no_match.id]

    async def it_boosts_books_matching_the_searched_author(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        matching_author = BookSearchResultFactory.build(title="A Tale", authors=["J.R.R. Tolkien"])
        other_author = BookSearchResultFactory.build(title="A Tale", authors=["Someone Else"])
        book_provider.fetch_volumes.return_value = {"books": [other_author, matching_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author="J.R.R. Tolkien",
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items[0].id == matching_author.id

    async def it_ranks_a_more_complete_entry_above_an_equally_relevant_sparse_one(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        complete_book = BookSearchResultFactory.build(title="A Tale")
        sparse_book = BookSearchResultFactory.build(
            title="A Tale",
            authors=[],
            year=None,
            isbn_10=None,
            isbn_13=None,
            cover_url=None,
        )
        book_provider.fetch_volumes.return_value = {"books": [sparse_book, complete_book], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author=None,
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert [b.id for b in result.items] == [complete_book.id, sparse_book.id]

    async def it_ranks_an_isbn_match_above_a_much_better_title_match(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        isbn_match = BookSearchResultFactory.build(title="Completely Different Title", isbn_10="0261102214")
        title_match = BookSearchResultFactory.build(title="The Hobbit")
        book_provider.fetch_volumes.return_value = {"books": [title_match, isbn_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn="0261102214",
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items[0].id == isbn_match.id

    async def it_falls_back_to_normal_ranking_when_no_result_matches_the_searched_isbn(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        close_match = BookSearchResultFactory.build(title="The Hobbit")
        far_match = BookSearchResultFactory.build(title="Completely Unrelated Book")
        book_provider.fetch_volumes.return_value = {"books": [far_match, close_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit",
            author=None,
            isbn="0261102214",
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert [b.id for b in result.items] == [close_match.id, far_match.id]

    async def it_prefers_a_verified_author_match_over_a_book_missing_author_data(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        cache_repo.find.return_value = None
        no_author_data = BookSearchResultFactory.build(title="A Tale", authors=[])
        verified_author = BookSearchResultFactory.build(title="A Tale", authors=["J.R.R. Tolkien"])
        book_provider.fetch_volumes.return_value = {"books": [no_author_data, verified_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale",
            author="J.R.R. Tolkien",
            isbn=None,
            preferred_languages=[],
            page=1,
            limit=10,
        )

        assert result.items[0].id == verified_author.id


def describe_get_external_book_details():
    async def it_raises_when_no_external_book_provider_is_configured(cache_repo: AsyncMock, book_repo: AsyncMock):
        service = BookService(cache_repo, book_repo, AsyncMock(spec=ReadBookRepository), providers=[])

        with pytest.raises(GatewayConfigurationError):
            await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

    async def it_raises_when_the_provider_cannot_find_the_book(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        book_provider.fetch_volume_details.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookDetailsNotFoundError):
            await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

    async def it_returns_the_details_from_the_matching_provider(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        details = BookDetailsFactory.build(page_count=42, description="A book", categories=[])
        book_provider.fetch_volume_details.return_value = details
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

        assert result is details


def describe_search_external_books_configuration():
    async def it_raises_when_no_external_book_provider_is_configured(cache_repo: AsyncMock, book_repo: AsyncMock):
        service = BookService(cache_repo, book_repo, AsyncMock(spec=ReadBookRepository), providers=[])

        with pytest.raises(GatewayConfigurationError):
            await service.search_external_books(
                title="The Hobbit",
                author=None,
                isbn=None,
                preferred_languages=[],
                page=1,
                limit=10,
            )


def _book_document(**overrides) -> BookModel:
    defaults = {
        "external_id": "google-books__abc123",
        "title": "The Hobbit",
        "created_at": datetime.now(UTC),
    }
    return BookFactory.build(**{**defaults, **overrides})


def describe_get_by_identifier():
    async def it_looks_up_by_external_id_when_the_identifier_contains_a_provider_prefix(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        identifier = BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")
        book_repo.find_by_identifier.return_value = _book_document()
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_book_by_identifier(identifier)

        assert result.title == "The Hobbit"
        book_repo.find_by_identifier.assert_awaited_once_with(identifier)

    async def it_looks_up_by_isbn_when_the_identifier_has_no_provider_prefix(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        book_repo.find_by_identifier.return_value = _book_document(isbn_10="0261102214")
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_book_by_identifier("0261102214")

        assert result.isbn_10 == "0261102214"
        book_repo.find_by_identifier.assert_awaited_once_with("0261102214")

    async def it_raises_when_the_external_id_does_not_match_any_book(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        book_repo.find_by_identifier.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookNotFoundError):
            await service.get_book_by_identifier(BookProviderIdentifier(BookProviderName.GOOGLE, "missing"))

    async def it_raises_when_the_isbn_does_not_match_any_book(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        book_repo.find_by_identifier.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookNotFoundError):
            await service.get_book_by_identifier("9780345339683")


def describe_get_rating_stats():
    async def it_delegates_to_the_read_book_repository(
        cache_repo: AsyncMock,
        book_repo: AsyncMock,
        book_provider: AsyncMock,
    ):
        read_book_repo = AsyncMock(spec=ReadBookRepository)
        read_book_repo.find_rating_stats_by_book_id.return_value = RatingStats(average_rating=4.5, rating_count=2)
        service = _service(cache_repo, book_repo, book_provider, read_book_repo=read_book_repo)
        book_id = PydanticObjectId()

        result = await service.get_rating_stats(book_id)

        assert result.average_rating == 4.5
        assert result.rating_count == 2
        read_book_repo.find_rating_stats_by_book_id.assert_awaited_once_with(book_id)
