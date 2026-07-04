from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.exceptions import InviteLinkDeactivatedError, UnauthorizedClubMemberError
from canterlot.models import ClubModel

SOME_CLUB_ID = "507f1f77bcf86cd799439011"


def describe_create_club():
    def it_creates_a_club_and_returns_it(client: TestClient, club_service: AsyncMock, invite_service: AsyncMock):
        club_service.create_new_club.return_value = ClubModel(name="Book Club")

        response = client.post("/api/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 201
        assert response.json()["name"] == "Book Club"
        invite_service.rotate_public_link.assert_awaited_once()

    def it_returns_422_for_a_name_that_is_too_short(client: TestClient, club_service: AsyncMock):
        response = client.post("/api/v1/clubs", json={"name": "ab"})

        assert response.status_code == 422
        club_service.create_new_club.assert_not_called()

    def it_returns_403_when_the_initial_invite_link_cannot_be_rotated(
        client: TestClient, club_service: AsyncMock, invite_service: AsyncMock
    ):
        club_service.create_new_club.return_value = ClubModel(name="Book Club")
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("cannot rotate")

        response = client.post("/api/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 403


def describe_rotate_public_admission_link():
    def it_returns_the_new_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.rotate_public_link.return_value = "new-token"

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/rotate")

        assert response.status_code == 201
        assert response.json()["invite_token"] == "new-token"

    def it_returns_403_when_the_requester_lacks_permission(client: TestClient, invite_service: AsyncMock):
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("nope")

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/rotate")

        assert response.status_code == 403


def describe_create_direct_invite():
    def it_returns_the_new_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.create_direct_invite.return_value = "direct-token"

        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/direct", json={"email": "alice@example.com"})

        assert response.status_code == 201
        assert response.json()["invite_token"] == "direct-token"

    def it_returns_422_for_an_invalid_email(client: TestClient, invite_service: AsyncMock):
        response = client.post(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/direct", json={"email": "not-an-email"})

        assert response.status_code == 422
        invite_service.create_direct_invite.assert_not_called()


def describe_get_public_invite():
    def it_returns_the_active_public_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.get_public_link.return_value = "public-token"

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/public")

        assert response.status_code == 200
        assert response.json() == "public-token"

    def it_returns_410_when_there_is_no_active_link(client: TestClient, invite_service: AsyncMock):
        invite_service.get_public_link.side_effect = InviteLinkDeactivatedError("gone")

        response = client.get(f"/api/v1/clubs/{SOME_CLUB_ID}/invites/public")

        assert response.status_code == 410
        assert response.json()["error"]["error_code"] == "INVITE_LINK_DEACTIVATED"
