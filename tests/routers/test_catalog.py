from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.exceptions import ClubSuggestionsClosedError, UnauthorizedClubMemberError
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
