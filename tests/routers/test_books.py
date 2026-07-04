from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError
from canterlot.models import BookDetails, BookModel

SOME_BOOK_ID = "507f1f77bcf86cd799439011"


def describe_get_external_book_details():
    def it_returns_book_details_on_success(client: TestClient, book_service: AsyncMock):
        book_service.get_external_book_details.return_value = BookDetails(
            page_count=42, description="A book", categories=[]
        )

        response = client.get("/api/v1/books/external/some-id", params={"provider": "google-books"})

        assert response.status_code == 200
        assert response.json()["page_count"] == 42

    def it_returns_404_when_the_provider_cannot_find_the_book(client: TestClient, book_service: AsyncMock):
        book_service.get_external_book_details.side_effect = BookDetailsNotFoundError("not found")

        response = client.get("/api/v1/books/external/some-id", params={"provider": "google-books"})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "EXTERNAL_BOOK_DETAILS_NOT_FOUND"

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, book_service: AsyncMock):
        response = client.get("/api/v1/books/external/some-id", params={"provider": "not-a-real-provider"})

        assert response.status_code == 422
        book_service.get_external_book_details.assert_not_called()


def describe_get_book():
    def it_returns_a_book_by_id(client: TestClient, book_service: AsyncMock):
        book_service.get_by_id.return_value = BookModel.model_validate(
            {"provider": "google-books", "title": "The Hobbit", "cover_url": "https://example.com/c.jpg"}
        )

        response = client.get(f"/api/v1/books/{SOME_BOOK_ID}")

        assert response.status_code == 200
        assert response.json()["title"] == "The Hobbit"

    def it_returns_404_when_the_book_does_not_exist(client: TestClient, book_service: AsyncMock):
        book_service.get_by_id.side_effect = BookNotFoundError("not found")

        response = client.get(f"/api/v1/books/{SOME_BOOK_ID}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"

    def it_returns_422_for_a_malformed_book_id(client: TestClient, book_service: AsyncMock):
        response = client.get("/api/v1/books/not-a-valid-object-id")

        assert response.status_code == 422
        book_service.get_by_id.assert_not_called()
