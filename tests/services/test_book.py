import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from canterlot.dto.book import BookDetails, BookSearchResult
from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError, BookSearchCriteriaMissingError
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.enums import BookProviderName
from canterlot.services.book import BookService


def _book_payload(**overrides) -> dict:
    defaults = {
        "id": "google-books__b1",
        "title": "The Hobbit",
        "authors": [],
        "languages": [],
        "cover_url": "https://example.com/c.jpg",
    }
    return {**defaults, **overrides}


def _service(cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock) -> BookService:
    book_provider.name = BookProviderName.GOOGLE
    return BookService(cache_repo, book_repo, [book_provider])


def describe_search_external_books_validation():
    async def it_raises_when_title_author_and_isbn_are_all_missing(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookSearchCriteriaMissingError):
            await service.search_external_books(
                title=None, author=None, isbn=None, preferred_languages=[], page=1, limit=10
            )

        book_provider.fetch_volumes.assert_not_called()

    async def it_does_not_crash_building_the_cache_key_when_title_is_none(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = {"books": [_book_payload()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title=None, author=None, isbn="0261102214", preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1

    async def it_ranks_by_author_alone_when_title_is_not_given(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        matching_author = _book_payload(id="google-books__matching", title="Anything", authors=["J.R.R. Tolkien"])
        other_author = _book_payload(id="google-books__other", title="Anything", authors=["Someone Else"])
        book_provider.fetch_volumes.return_value = {"books": [other_author, matching_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title=None, author="J.R.R. Tolkien", isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.items[0].id.book_id == "matching"


def describe_search_external_books_cache_behavior():
    async def it_returns_cached_results_without_contacting_providers(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = json.dumps({"books": [_book_payload()], "total_results": 1})
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1
        assert result.total_items == 1
        book_provider.fetch_volumes.assert_not_called()

    async def it_falls_back_to_a_live_fetch_when_the_cache_entry_is_corrupt(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = "not valid json"
        book_provider.fetch_volumes.return_value = {"books": [_book_payload()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1
        book_provider.fetch_volumes.assert_awaited_once()

    async def it_falls_back_to_a_live_fetch_when_the_cache_entry_is_missing_expected_keys(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = json.dumps({"books": [_book_payload()]})
        book_provider.fetch_volumes.return_value = {"books": [_book_payload()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1
        book_provider.fetch_volumes.assert_awaited_once()

    async def it_saves_a_json_serializable_payload_to_the_cache_on_a_miss(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = {"books": [_book_payload()], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        cache_repo.save.assert_awaited_once()
        cached_json = cache_repo.save.call_args.args[1]
        parsed = json.loads(cached_json)
        assert parsed["books"][0]["cover_url"] == "https://example.com/c.jpg"


def describe_search_external_books_provider_aggregation():
    async def it_skips_a_provider_that_raises(cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.side_effect = RuntimeError("upstream is down")
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.items == []
        assert result.total_pages == 0

    async def it_skips_a_provider_returning_an_unexpected_payload_shape(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        book_provider.fetch_volumes.return_value = "not-a-dict"
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.items == []

    async def it_skips_a_malformed_book_payload_but_keeps_the_valid_ones(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        malformed = {"id": "google-books__bad"}
        book_provider.fetch_volumes.return_value = {"books": [malformed, _book_payload()], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1

    async def it_leaves_the_cover_url_unset_when_no_provider_supplied_one(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        no_cover = _book_payload(cover_url=None)
        book_provider.fetch_volumes.return_value = {"books": [no_cover], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1
        assert result.items[0].cover_url is None

    async def it_accepts_a_provider_returning_an_already_built_book_search_result(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        prebuilt = BookSearchResult.model_validate(_book_payload())
        book_provider.fetch_volumes.return_value = {"books": [prebuilt], "total_results": 1}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.items) == 1
        assert result.items[0].id.provider == BookProviderName.GOOGLE


def describe_search_external_books_scoring():
    async def it_ranks_the_closest_title_match_first(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        close_match = _book_payload(id="google-books__close", title="The Hobbit")
        far_match = _book_payload(id="google-books__far", title="Completely Unrelated Book")
        book_provider.fetch_volumes.return_value = {"books": [far_match, close_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert [b.id.book_id for b in result.items] == ["close", "far"]

    async def it_boosts_books_matching_a_preferred_language(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        english = _book_payload(id="google-books__en-book", title="A Tale", languages=["en"])
        spanish = _book_payload(id="google-books__es-book", title="A Tale", languages=["es"])
        book_provider.fetch_volumes.return_value = {"books": [spanish, english], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author=None, isbn=None, preferred_languages=["en"], page=1, limit=10
        )

        assert result.items[0].id.book_id == "en-book"

    async def it_ranks_an_exact_language_match_above_a_same_base_language_match(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        exact = _book_payload(id="google-books__pt-br-book", title="A Tale", languages=["pt-BR"])
        base_only = _book_payload(id="google-books__pt-pt-book", title="A Tale", languages=["pt-PT"])
        book_provider.fetch_volumes.return_value = {"books": [base_only, exact], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author=None, isbn=None, preferred_languages=["pt-BR"], page=1, limit=10
        )

        assert [b.id.book_id for b in result.items] == ["pt-br-book", "pt-pt-book"]

    async def it_boosts_a_same_base_language_match_above_no_language_match(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        base_only = _book_payload(id="google-books__pt-pt-book", title="A Tale", languages=["pt-PT"])
        no_match = _book_payload(id="google-books__es-book", title="A Tale", languages=["es"])
        book_provider.fetch_volumes.return_value = {"books": [no_match, base_only], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author=None, isbn=None, preferred_languages=["pt-BR"], page=1, limit=10
        )

        assert [b.id.book_id for b in result.items] == ["pt-pt-book", "es-book"]

    async def it_boosts_books_matching_the_searched_author(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        matching_author = _book_payload(id="google-books__matching", title="A Tale", authors=["J.R.R. Tolkien"])
        other_author = _book_payload(id="google-books__other", title="A Tale", authors=["Someone Else"])
        book_provider.fetch_volumes.return_value = {"books": [other_author, matching_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author="J.R.R. Tolkien", isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.items[0].id.book_id == "matching"

    async def it_ranks_a_more_complete_entry_above_an_equally_relevant_sparse_one(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        complete_book = _book_payload(
            id="google-books__complete",
            title="A Tale",
            authors=["Some Author"],
            year=2000,
            isbn_10="0261102214",
            cover_url="https://example.com/c.jpg",
        )
        sparse_book = _book_payload(id="google-books__sparse", title="A Tale", authors=[], cover_url=None)
        book_provider.fetch_volumes.return_value = {"books": [sparse_book, complete_book], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert [b.id.book_id for b in result.items] == ["complete", "sparse"]

    async def it_ranks_an_isbn_match_above_a_much_better_title_match(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        isbn_match = _book_payload(
            id="google-books__isbn-match", title="Completely Different Title", isbn_10="0261102214"
        )
        title_match = _book_payload(id="google-books__title-match", title="The Hobbit")
        book_provider.fetch_volumes.return_value = {"books": [title_match, isbn_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn="0261102214", preferred_languages=[], page=1, limit=10
        )

        assert result.items[0].id.book_id == "isbn-match"

    async def it_falls_back_to_normal_ranking_when_no_result_matches_the_searched_isbn(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        close_match = _book_payload(id="google-books__close", title="The Hobbit")
        far_match = _book_payload(id="google-books__far", title="Completely Unrelated Book")
        book_provider.fetch_volumes.return_value = {"books": [far_match, close_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn="0261102214", preferred_languages=[], page=1, limit=10
        )

        assert [b.id.book_id for b in result.items] == ["close", "far"]

    async def it_prefers_a_verified_author_match_over_a_book_missing_author_data(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        no_author_data = _book_payload(id="google-books__no-author", title="A Tale", authors=[])
        verified_author = _book_payload(id="google-books__verified-author", title="A Tale", authors=["J.R.R. Tolkien"])
        book_provider.fetch_volumes.return_value = {"books": [no_author_data, verified_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author="J.R.R. Tolkien", isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.items[0].id.book_id == "verified-author"


def describe_get_external_book_details():
    async def it_raises_for_an_unknown_provider(cache_repo: AsyncMock, book_repo: AsyncMock):
        service = BookService(cache_repo, book_repo, providers=[])

        with pytest.raises(BookDetailsNotFoundError):
            await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

    async def it_raises_when_the_provider_cannot_find_the_book(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_provider.fetch_volume_details.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookDetailsNotFoundError):
            await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

    async def it_returns_the_details_from_the_matching_provider(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        details = BookDetails(page_count=42, description="A book", categories=[])
        book_provider.fetch_volume_details.return_value = details
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_external_book_details("some-id", BookProviderName.GOOGLE)

        assert result is details


def _book_document(**overrides) -> BookModel:
    defaults = {
        "external_id": "google-books__abc123",
        "title": "The Hobbit",
        "created_at": datetime.now(UTC),
    }
    return BookModel(**{**defaults, **overrides})


def describe_get_by_identifier():
    async def it_looks_up_by_external_id_when_the_identifier_contains_a_provider_prefix(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_repo.find_by_external_id.return_value = _book_document()
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_by_identifier(BookProviderIdentifier(BookProviderName.GOOGLE, "abc123"))

        assert result.title == "The Hobbit"
        book_repo.find_by_external_id.assert_awaited_once()
        book_repo.find_by_isbn.assert_not_called()

    async def it_looks_up_by_isbn_when_the_identifier_has_no_provider_prefix(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_repo.find_by_isbn.return_value = _book_document(isbn_10="0261102214")
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.get_by_identifier("0261102214")

        assert result.isbn_10 == "0261102214"
        book_repo.find_by_isbn.assert_awaited_once_with("0261102214", None)
        book_repo.find_by_external_id.assert_not_called()

    async def it_raises_when_the_external_id_does_not_match_any_book(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_repo.find_by_external_id.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookNotFoundError):
            await service.get_by_identifier(BookProviderIdentifier(BookProviderName.GOOGLE, "missing"))

    async def it_raises_when_the_isbn_does_not_match_any_book(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_repo.find_by_isbn.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookNotFoundError):
            await service.get_by_identifier("9780345339683")
