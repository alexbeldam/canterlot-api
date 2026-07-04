from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.exceptions import BookSearchCriteriaMissingError, ClubSuggestionsClosedError, UnauthorizedClubMemberError
from canterlot.models import PaginatedBooksResponse
from canterlot.models.catalog import SuggestionResponse, SuggestionStatus

SOME_CLUB_ID = "507f1f77bcf86cd799439011"


def _suggestion_payload(**overrides) -> dict:
    defaults = {
        "source_id": "ext-1",
        "provider": "google-books",
        "title": "The Hobbit",
        "cover_url": "https://example.com/c.jpg",
        "description": "A hobbit's tale",
    }
    return {**defaults, **overrides}


def describe_suggest_book_to_club():
    def it_returns_the_suggestion_result_on_success(client: TestClient, catalog_service: AsyncMock):
        catalog_service.suggest_book_to_club.return_value = SuggestionResponse(
            status=SuggestionStatus.SUCCESS, book_id=PydanticObjectId()
        )

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/", json=_suggestion_payload())

        assert response.status_code == 201
        assert response.json()["status"] == "SUCCESS"

    def it_returns_403_when_the_user_is_not_a_club_member(client: TestClient, catalog_service: AsyncMock):
        catalog_service.suggest_book_to_club.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/", json=_suggestion_payload())

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_403_when_suggestions_are_closed(client: TestClient, catalog_service: AsyncMock):
        catalog_service.suggest_book_to_club.side_effect = ClubSuggestionsClosedError("closed")

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/", json=_suggestion_payload())

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "CLUB_SUGGESTIONS_CLOSED"

    def it_returns_422_when_the_payload_is_missing_required_fields(client: TestClient, catalog_service: AsyncMock):
        response = client.post(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/", json={"source_id": "ext-1", "provider": "google-books"}
        )

        assert response.status_code == 422
        catalog_service.suggest_book_to_club.assert_not_called()

    def it_returns_422_for_a_malformed_club_id(client: TestClient, catalog_service: AsyncMock):
        response = client.post("/api/v1/clubs/not-a-valid-id/catalog/", json=_suggestion_payload())

        assert response.status_code == 422
        catalog_service.suggest_book_to_club.assert_not_called()


def describe_search_external_books_for_club():
    def it_returns_paginated_results_from_the_book_service(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock
    ):
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=1, total_results=0
        )

        response = client.get(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external", params={"title": "The Hobbit"}
        )

        assert response.status_code == 200
        assert response.json()["total_results"] == 0
        book_service.search_external_books.assert_awaited_once()

    def it_allows_a_search_with_isbn_alone_and_no_title(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock
    ):
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=1, total_results=0
        )

        response = client.get(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external", params={"isbn": "9780345339683"}
        )

        assert response.status_code == 200
        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["title"] is None
        assert call_kwargs["isbn"] == "9780345339683"

    def it_resolves_preferred_languages_from_the_club_instead_of_the_query(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock
    ):
        club_service.get_preferred_languages.return_value = ["en", "pt-BR"]
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=1, total_results=0
        )

        client.get(f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external", params={"title": "The Hobbit"})

        club_service.get_preferred_languages.assert_awaited_once()
        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["preferred_languages"] == ["en", "pt-BR"]

    def it_propagates_search_limit_and_page_query_params(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock
    ):
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.return_value = PaginatedBooksResponse(
            books=[], total_pages=0, current_page=2, total_results=0
        )

        client.get(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external",
            params={"title": "The Hobbit", "page": 2, "limit": 20},
        )

        call_kwargs = book_service.search_external_books.call_args.kwargs
        assert call_kwargs["page"] == 2
        assert call_kwargs["limit"] == 20

    def it_returns_403_when_the_user_is_not_a_club_member(client: TestClient, club_service: AsyncMock):
        club_service.get_preferred_languages.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.get(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external", params={"title": "The Hobbit"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_400_when_no_search_criteria_are_given(
        client: TestClient, club_service: AsyncMock, book_service: AsyncMock
    ):
        club_service.get_preferred_languages.return_value = []
        book_service.search_external_books.side_effect = BookSearchCriteriaMissingError("missing criteria")

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external")

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "BOOK_SEARCH_CRITERIA_MISSING"

    def it_returns_422_for_a_malformed_club_id(client: TestClient, club_service: AsyncMock, book_service: AsyncMock):
        response = client.get(
            "/api/v1/clubs/not-a-valid-id/catalog/search/external", params={"title": "The Hobbit"}
        )

        assert response.status_code == 422
        club_service.get_preferred_languages.assert_not_called()
        book_service.search_external_books.assert_not_called()

    def it_returns_500_with_the_error_envelope_on_an_unexpected_failure(client: TestClient, club_service: AsyncMock):
        club_service.get_preferred_languages.side_effect = RuntimeError("cache is on fire")

        response = client.get(
            f"/api/v1/clubs/{SOME_CLUB_ID}/catalog/search/external", params={"title": "The Hobbit"}
        )

        assert response.status_code == 500
        assert response.json()["error"]["error_code"] == "INTERNAL_SERVER_ERROR"
