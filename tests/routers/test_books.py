from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.exceptions import BookDetailsNotFoundError, BookNotFoundError
from canterlot.models import BookDetails, BookModel, PaginatedBooksResponse

SOME_BOOK_ID = "507f1f77bcf86cd799439011"


def describe_search_external_books():
    def it_returns_paginated_results_from_the_book_service(client: TestClient, book_service: AsyncMock):
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=1, total_results=0
        )

        response = client.get("/api/v1/books/external", params={"title": "The Hobbit"})

        assert response.status_code == 200
        assert response.json()["total_results"] == 0
        book_service.search_external_books.assert_awaited_once()

    def it_returns_422_when_the_title_is_missing(client: TestClient, book_service: AsyncMock):
        response = client.get("/api/v1/books/external")

        assert response.status_code == 422
        book_service.search_external_books.assert_not_called()

    def it_propagates_search_limit_and_page_query_params(client: TestClient, book_service: AsyncMock):
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=2, total_results=0
        )

        client.get("/api/v1/books/external", params={"title": "The Hobbit", "page": 2, "limit": 20})

        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["page"] == 2
        assert call_kwargs["limit"] == 20

    def it_returns_500_with_the_error_envelope_on_an_unexpected_failure(client: TestClient, book_service: AsyncMock):
        book_service.search_external_books.side_effect = RuntimeError("cache is on fire")

        response = client.get("/api/v1/books/external", params={"title": "The Hobbit"})

        assert response.status_code == 500
        assert response.json()["error"]["error_code"] == "INTERNAL_SERVER_ERROR"


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
