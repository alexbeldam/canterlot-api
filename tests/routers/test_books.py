from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.dto.book import BookDetails, BookResponse, PaginatedBooksResponse
from canterlot.exceptions import (
    BookDetailsNotFoundError,
    BookNotFoundError,
    BookSearchCriteriaMissingError,
    UnauthorizedClubMemberError,
)
from canterlot.models.book import BookProviderIdentifier
from canterlot.models.enums import BookProviderName

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_SLUG = "book-club"


def _book_response(**overrides) -> BookResponse:
    defaults = {
        "external_id": "google-books__abc123",
        "title": "The Hobbit",
        "cover_url": "https://example.com/c.jpg",
        "created_at": datetime.now(UTC),
    }
    return BookResponse.model_validate({**defaults, **overrides})


def describe_get_external_book_details():
    def it_returns_book_details_on_success(client: TestClient, book_service: AsyncMock):
        book_service.get_external_book_details.return_value = BookDetails(
            page_count=42, description="A book", categories=[]
        )

        response = client.get("/v1/books/external/google-books__some-id")

        assert response.status_code == 200
        assert response.json()["page_count"] == 42
        book_service.get_external_book_details.assert_awaited_once_with("some-id", BookProviderName.GOOGLE)

    def it_returns_404_when_the_provider_cannot_find_the_book(client: TestClient, book_service: AsyncMock):
        book_service.get_external_book_details.side_effect = BookDetailsNotFoundError("not found")

        response = client.get("/v1/books/external/google-books__some-id")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "EXTERNAL_BOOK_DETAILS_NOT_FOUND"

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, book_service: AsyncMock):
        response = client.get("/v1/books/external/not-a-real-provider__some-id")

        assert response.status_code == 422
        book_service.get_external_book_details.assert_not_called()

    def it_returns_422_for_an_identifier_missing_the_provider_prefix(client: TestClient, book_service: AsyncMock):
        response = client.get("/v1/books/external/some-id")

        assert response.status_code == 422
        book_service.get_external_book_details.assert_not_called()


def describe_get_book():
    def it_returns_a_book_by_external_id(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.return_value = _book_response()

        response = client.get("/v1/books/google-books__abc123")

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "The Hobbit"
        assert body["external_id"] == "google-books__abc123"
        assert "id" not in body
        book_service.get_by_identifier.assert_awaited_once_with(
            BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")
        )

    def it_returns_a_book_by_isbn(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.return_value = _book_response(isbn_10="0261102214")

        response = client.get("/v1/books/0261102214")

        assert response.status_code == 200
        assert response.json()["isbn_10"] == "0261102214"
        book_service.get_by_identifier.assert_awaited_once_with("0261102214")

    def it_returns_404_when_the_book_does_not_exist(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.side_effect = BookNotFoundError("not found")

        response = client.get("/v1/books/google-books__missing")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"

    def it_returns_422_for_an_identifier_that_is_neither_a_valid_external_id_nor_an_isbn(
        client: TestClient, book_service: AsyncMock
    ):
        response = client.get("/v1/books/not-a-valid-identifier")

        assert response.status_code == 422
        book_service.get_by_identifier.assert_not_called()


def describe_search_external_books():
    def it_returns_paginated_results_from_the_book_service(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            items=[], total_items=0, current_page=1, page_size=5
        )

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit"})

        assert response.status_code == 200
        assert response.json()["total_items"] == 0
        book_service.search_external_books.assert_awaited_once()

    def it_returns_422_when_no_club_slug_is_given(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        response = client.get("/v1/books/external", params={"title": "The Hobbit"})

        assert response.status_code == 422
        club_repo.find_id_by_slug.assert_not_called()
        club_service.get_preferred_languages.assert_not_called()
        book_service.search_external_books.assert_not_called()

    def it_allows_a_search_with_isbn_alone_and_no_title(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            items=[], total_items=0, current_page=1, page_size=5
        )

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "isbn": "9780345339683"})

        assert response.status_code == 200
        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["title"] is None
        assert call_kwargs["isbn"] == "9780345339683"

    def it_resolves_preferred_languages_from_the_club_instead_of_the_query(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.return_value = ["en", "pt-BR"]
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            items=[], total_items=0, current_page=1, page_size=5
        )

        client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit"})

        club_service.get_preferred_languages.assert_awaited_once()
        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["preferred_languages"] == ["en", "pt-BR"]

    def it_propagates_search_limit_and_page_query_params(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            items=[], total_items=0, current_page=2, page_size=5
        )

        client.get(
            "/v1/books/external",
            params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit", "page": 2, "limit": 20},
        )

        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["page"] == 2
        assert call_kwargs["limit"] == 20

    def it_returns_403_when_the_user_is_not_a_club_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit"})

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_400_when_no_search_criteria_are_given(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.side_effect = BookSearchCriteriaMissingError("missing criteria")

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG})

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "BOOK_SEARCH_CRITERIA_MISSING"

    def it_returns_404_when_the_club_slug_does_not_exist(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = None

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit"})

        assert response.status_code == 404
        club_service.get_preferred_languages.assert_not_called()
        book_service.search_external_books.assert_not_called()

    def it_returns_500_with_the_error_envelope_on_an_unexpected_failure(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.get_preferred_languages.side_effect = RuntimeError("cache is on fire")

        response = client.get("/v1/books/external", params={"club_slug": SOME_CLUB_SLUG, "title": "The Hobbit"})

        assert response.status_code == 500
        assert response.json()["error"]["error_code"] == "INTERNAL_SERVER_ERROR"
