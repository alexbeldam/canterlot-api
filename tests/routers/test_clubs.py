from types import SimpleNamespace
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.exceptions import InviteLinkDeactivatedError, UnauthorizedClubMemberError
from canterlot.models.club import ClubModel, MemberSchema
from canterlot.models.enums import UserRole

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_SLUG = "book-club"
SOME_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439011")  # matches conftest's `current_user` fixture


def _found_club(club_id: PydanticObjectId = SOME_CLUB_ID) -> SimpleNamespace:
    return SimpleNamespace(id=club_id)


def _created_club() -> ClubModel:
    return ClubModel(
        name="Book Club",
        slug="book-club",
        members=[MemberSchema(user_id=SOME_OWNER_ID, role=UserRole.OWNER)],
    )


def describe_create_club():
    def it_creates_a_club_and_returns_it(
        client: TestClient, club_service: AsyncMock, invite_service: AsyncMock, user_repo: AsyncMock
    ):
        club_service.create_new_club.return_value = _created_club()
        user_repo.find_username_by_id.return_value = "alice_1"

        response = client.post("/api/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Book Club"
        assert body["slug"] == "book-club"
        assert body["members"][0]["username"] == "alice_1"
        assert body["members"][0]["role"] == "OWNER"
        assert "id" not in body
        invite_service.rotate_public_link.assert_awaited_once()

    def it_does_not_leak_the_internal_object_id(client: TestClient, club_service: AsyncMock, user_repo: AsyncMock):
        club_service.create_new_club.return_value = _created_club()
        user_repo.find_username_by_id.return_value = "alice_1"

        response = client.post("/api/v1/clubs", json={"name": "Book Club"})

        body = response.json()
        assert "id" not in body
        assert "_id" not in body

    def it_returns_422_for_a_name_that_is_too_short(client: TestClient, club_service: AsyncMock):
        response = client.post("/api/v1/clubs", json={"name": "ab"})

        assert response.status_code == 422
        club_service.create_new_club.assert_not_called()

    def it_returns_403_when_the_initial_invite_link_cannot_be_rotated(
        client: TestClient, club_service: AsyncMock, invite_service: AsyncMock
    ):
        club_service.create_new_club.return_value = _created_club()
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("cannot rotate")

        response = client.post("/api/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 403


def describe_rotate_public_admission_link():
    def it_returns_the_new_invite_token(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _found_club()
        invite_service.rotate_public_link.return_value = "new-token"

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/rotate")

        assert response.status_code == 201
        assert response.json()["invite_token"] == "new-token"

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = None

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/rotate")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_NOT_FOUND"

    def it_returns_403_when_the_requester_lacks_permission(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_by_slug.return_value = _found_club()
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("nope")

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/rotate")

        assert response.status_code == 403


def describe_create_direct_invite():
    def it_returns_the_new_invite_token(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _found_club()
        invite_service.create_direct_invite.return_value = "direct-token"

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/direct", json={"email": "alice@example.com"})

        assert response.status_code == 201
        assert response.json()["invite_token"] == "direct-token"

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = None

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/direct", json={"email": "alice@example.com"})

        assert response.status_code == 404

    def it_returns_422_for_an_invalid_email(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _found_club()

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/direct", json={"email": "not-an-email"})

        assert response.status_code == 422
        invite_service.create_direct_invite.assert_not_called()


def describe_get_public_invite():
    def it_returns_the_active_public_invite_token(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _found_club()
        invite_service.get_public_link.return_value = "public-token"

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 200
        assert response.json() == "public-token"

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_by_slug.return_value = None

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 404

    def it_returns_410_when_there_is_no_active_link(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_by_slug.return_value = _found_club()
        invite_service.get_public_link.side_effect = InviteLinkDeactivatedError("gone")

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 410
        assert response.json()["error"]["error_code"] == "INVITE_LINK_DEACTIVATED"
