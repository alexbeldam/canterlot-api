import json
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError
from canterlot.models import BookDetails, BookSearchResult
from canterlot.models.enums import BookProviderName
from canterlot.services.book import BookService

SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def _book_payload(**overrides) -> dict:
    defaults = {
        "id": "b1",
        "provider": BookProviderName.GOOGLE,
        "title": "The Hobbit",
        "authors": [],
        "languages": [],
        "cover_url": "https://example.com/c.jpg",
    }
    return {**defaults, **overrides}


def _service(cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock) -> BookService:
    book_provider.name = BookProviderName.GOOGLE
    return BookService(cache_repo, book_repo, [book_provider])


def describe_search_external_books_cache_behavior():
    async def it_returns_cached_results_without_contacting_providers(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = json.dumps({"books": [_book_payload()], "total_results": 1})
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.books) == 1
        assert result.total_results == 1
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

        assert len(result.books) == 1
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

        assert len(result.books) == 1
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

        assert result.books == []
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

        assert result.books == []

    async def it_skips_a_malformed_book_payload_but_keeps_the_valid_ones(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        malformed = {"id": "bad", "provider": BookProviderName.GOOGLE, "title": "No Cover"}
        book_provider.fetch_volumes.return_value = {"books": [malformed, _book_payload()], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert len(result.books) == 1

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

        assert len(result.books) == 1
        assert result.books[0].provider == BookProviderName.GOOGLE


def describe_search_external_books_scoring():
    async def it_ranks_the_closest_title_match_first(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        close_match = _book_payload(id="close", title="The Hobbit")
        far_match = _book_payload(id="far", title="Completely Unrelated Book")
        book_provider.fetch_volumes.return_value = {"books": [far_match, close_match], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="The Hobbit", author=None, isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert [b.id for b in result.books] == ["close", "far"]

    async def it_boosts_books_matching_a_preferred_language(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        english = _book_payload(id="en-book", title="A Tale", languages=["en"])
        spanish = _book_payload(id="es-book", title="A Tale", languages=["es"])
        book_provider.fetch_volumes.return_value = {"books": [spanish, english], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author=None, isbn=None, preferred_languages=["en"], page=1, limit=10
        )

        assert result.books[0].id == "en-book"

    async def it_boosts_books_matching_the_searched_author(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        cache_repo.find.return_value = None
        matching_author = _book_payload(id="matching", title="A Tale", authors=["J.R.R. Tolkien"])
        other_author = _book_payload(id="other", title="A Tale", authors=["Someone Else"])
        book_provider.fetch_volumes.return_value = {"books": [other_author, matching_author], "total_results": 2}
        service = _service(cache_repo, book_repo, book_provider)

        result = await service.search_external_books(
            title="A Tale", author="J.R.R. Tolkien", isbn=None, preferred_languages=[], page=1, limit=10
        )

        assert result.books[0].id == "matching"


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


def describe_get_by_id():
    async def it_raises_when_the_book_is_not_found(
        cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock
    ):
        book_repo.find_by_id.return_value = None
        service = _service(cache_repo, book_repo, book_provider)

        with pytest.raises(BookNotFoundError):
            await service.get_by_id(SOME_BOOK_ID)

    async def it_returns_the_book_when_found(cache_repo: AsyncMock, book_repo: AsyncMock, book_provider: AsyncMock):
        book_repo.find_by_id.return_value = "the-book"
        service = _service(cache_repo, book_repo, book_provider)

        assert await service.get_by_id(SOME_BOOK_ID) == "the-book"
