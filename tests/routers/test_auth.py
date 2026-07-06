from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.dto.auth import TokenResponse
from canterlot.dto.club import ClubOnboarding
from canterlot.exceptions import InvalidCredentialsError, UsernameAlreadyExistsError
from canterlot.models.enums import ClubOnboardingStatus
from canterlot.services.auth import RegisterResult
from canterlot.services.invite import InviteValidationResult

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def _register_payload(**overrides) -> dict:
    defaults = {"name": "Alice Smith", "username": "alice_1", "email": "alice@example.com", "password": "secret1"}
    return {**defaults, **overrides}


def describe_register():
    def it_registers_a_user_without_an_invite(client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock):
        auth_service.register_user.return_value = RegisterResult(
            access_token="access", refresh_token="refresh", user_id=SOME_USER_ID
        )

        response = client.post("/api/v1/auth/register", json=_register_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["access_token"] == "access"
        assert body["onboarding"] is None
        invite_service.validate_incoming_invite.assert_not_called()
        call_args = auth_service.register_user.call_args
        assert call_args.args[0].username == "alice_1"
        assert call_args.args[1] is None

    def it_registers_a_user_and_onboards_them_via_an_invite(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock, club_service: AsyncMock
    ):
        auth_service.register_user.return_value = RegisterResult(
            access_token="access", refresh_token="refresh", user_id=SOME_USER_ID
        )
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by="referrer_1", is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(club_name="Book Club", status=ClubOnboardingStatus.JOINED)

        response = client.post(
            "/api/v1/auth/register", params={"invite_id": "some-invite-id"}, json=_register_payload()
        )

        assert response.status_code == 201
        assert response.json()["onboarding"]["status"] == "JOINED"
        invite_service.register_invite_usage.assert_awaited_once_with("some-invite-id")

    def it_returns_409_when_the_username_is_taken(client: TestClient, auth_service: AsyncMock):
        auth_service.register_user.side_effect = UsernameAlreadyExistsError("taken")

        response = client.post("/api/v1/auth/register", json=_register_payload())

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "USERNAME_ALREADY_EXISTS"

    def it_returns_422_for_a_password_that_is_too_short(client: TestClient, auth_service: AsyncMock):
        response = client.post("/api/v1/auth/register", json=_register_payload(password="short"))

        assert response.status_code == 422
        auth_service.register_user.assert_not_called()


def describe_login():
    def it_returns_a_token_pair_for_valid_credentials(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.return_value = TokenResponse(access_token="access", refresh_token="refresh")

        response = client.post("/api/v1/auth/login", data={"username": "alice_1", "password": "secret1"})

        assert response.status_code == 200
        assert response.json()["access_token"] == "access"

    def it_returns_401_for_invalid_credentials(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.side_effect = InvalidCredentialsError("nope")

        response = client.post("/api/v1/auth/login", data={"username": "alice_1", "password": "wrong"})

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_CREDENTIALS"


def describe_refresh_token_rotation():
    def it_returns_a_rotated_token_pair(client: TestClient, auth_service: AsyncMock):
        auth_service.rotate_refresh_token.return_value = TokenResponse(
            access_token="new-access", refresh_token="new-refresh"
        )

        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        assert response.json()["access_token"] == "new-access"
        auth_service.rotate_refresh_token.assert_awaited_once_with(SOME_USER_ID, "old-refresh-token")
