from datetime import UTC, datetime
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.dto.book import BookDetails, BookResponse
from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError
from canterlot.models.enums import BookProviderName


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

        response = client.get("/api/v1/books/external/google-books__some-id")

        assert response.status_code == 200
        assert response.json()["page_count"] == 42
        book_service.get_external_book_details.assert_awaited_once_with("some-id", BookProviderName.GOOGLE)

    def it_returns_404_when_the_provider_cannot_find_the_book(client: TestClient, book_service: AsyncMock):
        book_service.get_external_book_details.side_effect = BookDetailsNotFoundError("not found")

        response = client.get("/api/v1/books/external/google-books__some-id")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "EXTERNAL_BOOK_DETAILS_NOT_FOUND"

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, book_service: AsyncMock):
        response = client.get("/api/v1/books/external/not-a-real-provider__some-id")

        assert response.status_code == 422
        book_service.get_external_book_details.assert_not_called()

    def it_returns_422_for_an_identifier_missing_the_provider_prefix(client: TestClient, book_service: AsyncMock):
        response = client.get("/api/v1/books/external/some-id")

        assert response.status_code == 422
        book_service.get_external_book_details.assert_not_called()


def describe_get_book():
    def it_returns_a_book_by_external_id(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.return_value = _book_response()

        response = client.get("/api/v1/books/google-books__abc123")

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "The Hobbit"
        assert body["external_id"] == "google-books__abc123"
        assert "id" not in body
        book_service.get_by_identifier.assert_awaited_once_with("google-books__abc123")

    def it_returns_a_book_by_isbn(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.return_value = _book_response(isbn_10="0261102214")

        response = client.get("/api/v1/books/0261102214")

        assert response.status_code == 200
        assert response.json()["isbn_10"] == "0261102214"
        book_service.get_by_identifier.assert_awaited_once_with("0261102214")

    def it_returns_404_when_the_book_does_not_exist(client: TestClient, book_service: AsyncMock):
        book_service.get_by_identifier.side_effect = BookNotFoundError("not found")

        response = client.get("/api/v1/books/google-books__missing")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"
