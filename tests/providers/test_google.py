from unittest.mock import AsyncMock

import pytest
from curl_cffi.requests import AsyncSession

from canterlot.exceptions import BookProviderUnavailableError
from canterlot.models.book import SearchParams
from canterlot.models.enums import BookProviderName
from canterlot.providers.google import GoogleBookProvider


def _response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> AsyncMock:
    response = AsyncMock()
    response.status_code = status_code
    response.json = lambda: json_data or {}
    response.text = text
    return response


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def provider(session: AsyncMock) -> GoogleBookProvider:
    return GoogleBookProvider(session, "AIzaSy-test")


def describe_name():
    def it_reports_google_as_its_provider_name(provider: GoogleBookProvider):
        assert provider.name == BookProviderName.GOOGLE


def describe_fetch_volumes():
    async def it_returns_an_empty_result_on_a_non_200_response(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(status_code=500, text="server error")

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert result == {"books": [], "total_results": 0}

    async def it_maps_a_volume_item_into_a_book_search_result(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(
            json_data={
                "totalItems": 1,
                "items": [
                    {
                        "id": "abc123",
                        "volumeInfo": {
                            "title": "The Hobbit",
                            "authors": ["J.R.R. Tolkien"],
                            "publishedDate": "1937-09-21",
                            "language": "en",
                            "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"},
                            "industryIdentifiers": [
                                {"type": "ISBN_10", "identifier": "0345339681"},
                                {"type": "ISBN_13", "identifier": "9780345339683"},
                            ],
                        },
                    }
                ],
            }
        )

        result = await provider.fetch_volumes(SearchParams(title="The Hobbit"), 0, 40)

        assert result["total_results"] == 1
        book = result["books"][0]
        assert book.id.book_id == "abc123"
        assert book.title == "The Hobbit"
        assert book.authors == ["J.R.R. Tolkien"]
        assert book.year == 1937
        assert book.isbn_10 == "0345339681"
        assert book.isbn_13 == "9780345339683"
        assert str(book.cover_url) == "https://books.google.com/cover.jpg"

    async def it_leaves_the_cover_url_unset_when_no_image_is_available(
        provider: GoogleBookProvider, session: AsyncMock
    ):
        session.get.return_value = _response(
            json_data={"totalItems": 1, "items": [{"id": "abc123", "volumeInfo": {"title": "No Cover"}}]}
        )

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert result["books"][0].cover_url is None

    async def it_defaults_to_an_empty_language_list_when_the_field_is_absent(
        provider: GoogleBookProvider, session: AsyncMock
    ):
        session.get.return_value = _response(
            json_data={"totalItems": 1, "items": [{"id": "abc123", "volumeInfo": {"title": "No Language"}}]}
        )

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert len(result["books"]) == 1
        assert result["books"][0].languages == []

    async def it_skips_a_volume_with_no_title(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(
            json_data={
                "totalItems": 2,
                "items": [
                    {"id": "no-title", "volumeInfo": {}},
                    {"id": "good", "volumeInfo": {"title": "Good Book"}},
                ],
            }
        )

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert len(result["books"]) == 1
        assert result["books"][0].id.book_id == "good"

    async def it_skips_a_volume_that_fails_validation(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(
            json_data={
                "totalItems": 2,
                "items": [
                    {
                        "id": "bad",
                        "volumeInfo": {
                            "title": "Bad ISBN",
                            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "not-a-real-isbn"}],
                        },
                    },
                    {"id": "good", "volumeInfo": {"title": "Good Book"}},
                ],
            }
        )

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert len(result["books"]) == 1
        assert result["books"][0].id.book_id == "good"

    async def it_ignores_non_string_industry_identifiers(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(
            json_data={
                "totalItems": 1,
                "items": [
                    {
                        "id": "abc123",
                        "volumeInfo": {
                            "title": "Weird Identifiers",
                            "industryIdentifiers": [{"type": "ISBN_10", "identifier": 12345}],
                        },
                    }
                ],
            }
        )

        result = await provider.fetch_volumes(SearchParams(), 0, 40)

        assert result["books"][0].isbn_10 is None

    async def it_builds_a_query_from_title_and_authors_when_no_isbn_is_given(
        provider: GoogleBookProvider, session: AsyncMock
    ):
        session.get.return_value = _response(json_data={"totalItems": 0, "items": []})

        params = SearchParams(title="The Hobbit", authors=["Tolkien"])
        await provider.fetch_volumes(params, 0, 40)

        call_kwargs = session.get.call_args.kwargs
        query = call_kwargs["params"]["q"]
        assert 'intitle:"The Hobbit"' in query
        assert 'inauthor:"Tolkien"' in query

    async def it_queries_by_isbn_alone_ignoring_title_and_authors(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(json_data={"totalItems": 0, "items": []})

        params = SearchParams(title="The Hobbit", authors=["Tolkien"], isbn="978-3-16-148410-0")
        await provider.fetch_volumes(params, 0, 40)

        call_kwargs = session.get.call_args.kwargs
        query = call_kwargs["params"]["q"]
        assert query == "isbn:9783161484100"

    async def it_sends_the_key_param_from_constructor(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(json_data={"totalItems": 0, "items": []})

        await provider.fetch_volumes(SearchParams(title="The Hobbit"), 0, 40)

        call_kwargs = session.get.call_args.kwargs
        assert call_kwargs["params"]["key"] == "AIzaSy-test"


def describe_fetch_volume_details():
    async def it_returns_none_on_a_404_response(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(status_code=404, text="not found")

        assert await provider.fetch_volume_details("abc123") is None

    async def it_raises_when_the_provider_returns_an_unexpected_status(
        provider: GoogleBookProvider, session: AsyncMock
    ):
        session.get.return_value = _response(status_code=503, text="Service temporarily unavailable.")

        with pytest.raises(BookProviderUnavailableError):
            await provider.fetch_volume_details("abc123")

    async def it_returns_book_details_on_success(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(
            json_data={
                "volumeInfo": {
                    "description": "A great book",
                    "pageCount": 310,
                    "categories": ["Fantasy"],
                }
            }
        )

        details = await provider.fetch_volume_details("abc123")

        assert details is not None
        assert details.description == "A great book"
        assert details.page_count == 310
        assert details.categories == ["Fantasy"]

    async def it_normalizes_a_blank_description_to_none(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(json_data={"volumeInfo": {"description": ""}})

        details = await provider.fetch_volume_details("abc123")

        assert details is not None
        assert details.description is None

    async def it_sends_the_key_param_for_volume_details(provider: GoogleBookProvider, session: AsyncMock):
        session.get.return_value = _response(json_data={"volumeInfo": {}})

        await provider.fetch_volume_details("abc123")

        call_kwargs = session.get.call_args.kwargs
        assert call_kwargs["params"]["key"] == "AIzaSy-test"


def describe_init():
    def it_raises_when_api_key_is_empty(session: AsyncMock):
        with pytest.raises(ValueError, match="requires a non-empty API key"):
            GoogleBookProvider(session, "")
