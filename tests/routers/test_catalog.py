from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.dto.catalog import CatalogEntryResponse, PaginatedCatalogResponse, SuggestionResponse, SuggestionStatus
from canterlot.exceptions import (
    BookNotFoundError,
    ClubSuggestionsClosedError,
    UnauthorizedClubMemberError,
)
from canterlot.models.book import BookProviderIdentifier
from canterlot.models.enums import BookProviderName

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_SLUG = "book-club"
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _suggestion_payload(**overrides) -> dict:
    defaults = {
        "source_id": "google-books__ext-1",
        "title": "The Hobbit",
        "cover_url": "https://example.com/c.jpg",
        "description": "A hobbit's tale",
    }
    return {**defaults, **overrides}


def describe_suggest_book_to_club():
    def it_returns_the_suggestion_result_on_success(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.suggest_book_to_club.return_value = SuggestionResponse(
            status=SuggestionStatus.SUCCESS,
            book_external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "ext-1"),
        )

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json=_suggestion_payload())

        assert response.status_code == 201
        assert response.json()["status"] == "SUCCESS"
        assert response.headers["Location"] == f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__ext-1"

    def it_returns_200_when_the_book_already_exists_in_the_catalog(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.suggest_book_to_club.return_value = SuggestionResponse(
            status=SuggestionStatus.ALREADY_EXISTS,
            book_external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "ext-1"),
        )

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json=_suggestion_payload())

        assert response.status_code == 200
        assert response.json()["status"] == "ALREADY_EXISTS"
        assert "Location" not in response.headers

    def it_returns_403_when_the_user_is_not_a_club_member(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.suggest_book_to_club.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json=_suggestion_payload())

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_403_when_suggestions_are_closed(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.suggest_book_to_club.side_effect = ClubSuggestionsClosedError("closed")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json=_suggestion_payload())

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "CLUB_SUGGESTIONS_CLOSED"

    def it_returns_422_when_the_payload_is_missing_required_fields(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json={"source_id": "google-books__ext-1"})

        assert response.status_code == 422
        catalog_service.suggest_book_to_club.assert_not_called()

    def it_returns_404_when_the_club_slug_does_not_exist(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = None

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", json=_suggestion_payload())

        assert response.status_code == 404
        catalog_service.suggest_book_to_club.assert_not_called()


def describe_get_club_catalog():
    def _entry_response(**overrides) -> CatalogEntryResponse:
        defaults = {
            "external_id": "google-books__ext-1",
            "title": "The Hobbit",
            "created_at": datetime.now(UTC),
            "suggested_by": "alice_1",
            "suggested_at": datetime.now(UTC),
        }
        return CatalogEntryResponse.model_validate({**defaults, **overrides})

    def it_returns_a_paginated_page_of_the_catalog(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.get_catalog_page.return_value = PaginatedCatalogResponse(
            items=[_entry_response()], total_items=1, current_page=1, page_size=20
        )

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/")

        assert response.status_code == 200
        body = response.json()
        assert body["total_items"] == 1
        assert body["items"][0]["suggested_by"] == "alice_1"

    def it_returns_403_when_the_caller_is_not_a_club_member(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.get_catalog_page.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_club_slug_does_not_exist(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = None

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/")

        assert response.status_code == 404
        catalog_service.get_catalog_page.assert_not_called()

    def it_passes_sort_and_filter_query_params_through(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        catalog_service.get_catalog_page.return_value = PaginatedCatalogResponse(
            items=[], total_items=0, current_page=1, page_size=20
        )

        response = client.get(
            f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/",
            params={"sort_by": "title", "suggested_by": "alice_1", "page": 2, "limit": 10, "q": "gatsby"},
        )

        assert response.status_code == 200
        catalog_service.get_catalog_page.assert_awaited_once()
        _, kwargs = catalog_service.get_catalog_page.call_args
        assert kwargs["sort_by"] == "title"
        assert kwargs["suggested_by"] == "alice_1"
        assert kwargs["page"] == 2
        assert kwargs["limit"] == 10
        assert kwargs["q"] == "gatsby"

    def it_returns_422_for_an_invalid_sort_field(client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/", params={"sort_by": "not-a-real-field"})

        assert response.status_code == 422
        catalog_service.get_catalog_page.assert_not_called()


def describe_remove_from_club():
    def it_returns_204_on_success(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock, book_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        book_repo.find_id_by_identifier.return_value = SOME_BOOK_ID

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__ext-1")

        assert response.status_code == 204
        catalog_service.remove_book_from_club.assert_awaited_once()

    def it_returns_403_when_the_caller_is_not_privileged_or_the_suggester(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock, book_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        book_repo.find_id_by_identifier.return_value = SOME_BOOK_ID
        catalog_service.remove_book_from_club.side_effect = UnauthorizedClubMemberError("not allowed")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__ext-1")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_book_is_not_in_the_catalog(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock, book_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        book_repo.find_id_by_identifier.return_value = SOME_BOOK_ID
        catalog_service.remove_book_from_club.side_effect = BookNotFoundError("not in catalog")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__ext-1")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"

    def it_returns_404_when_the_identifier_does_not_resolve_to_any_book(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock, book_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        book_repo.find_id_by_identifier.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__missing")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"
        catalog_service.remove_book_from_club.assert_not_called()

    def it_returns_404_when_the_club_slug_does_not_exist(
        client: TestClient, catalog_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/catalog/google-books__ext-1")

        assert response.status_code == 404
        catalog_service.remove_book_from_club.assert_not_called()
