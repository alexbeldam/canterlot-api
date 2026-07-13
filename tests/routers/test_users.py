from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.dto.auth import ConnectedProvidersResponse, LinkedProviderDTO, TokenResponse
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidOAuthCredentialError,
    LastAuthenticationMethodError,
    UsernameAlreadyExistsError,
)
from canterlot.models.enums import AuthProviderName
from canterlot.models.user import UserModel

SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def describe_get_connected_providers():
    def it_returns_the_connected_providers(client: TestClient, auth_service: AsyncMock):
        auth_service.list_connected_providers.return_value = ConnectedProvidersResponse(
            has_password=True,
            linked_providers=[LinkedProviderDTO(provider=AuthProviderName.GOOGLE, linked_at=datetime.now(UTC))],
        )

        response = client.get("/api/v1/users/me/auth-providers")

        assert response.status_code == 200
        body = response.json()
        assert body["has_password"] is True
        assert body["linked_providers"][0]["provider"] == "GOOGLE"


def describe_link_provider():
    def it_returns_204_when_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.return_value = None

        response = client.post("/api/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 204

    def it_returns_401_for_an_invalid_credential(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = InvalidOAuthCredentialError("bad token")

        response = client.post("/api/v1/users/me/auth-providers/GOOGLE", json={"credential": "garbage"})

        assert response.status_code == 401

    def it_returns_409_when_already_linked_to_a_different_account(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = AuthProviderAlreadyLinkedError("taken")

        response = client.post("/api/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "AUTH_PROVIDER_ALREADY_LINKED"

    def it_returns_503_when_the_provider_is_not_configured(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = GatewayConfigurationError("disabled")

        response = client.post("/api/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 503

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, auth_service: AsyncMock):
        response = client.post("/api/v1/users/me/auth-providers/FACEBOOK", json={"credential": "some-id-token"})

        assert response.status_code == 422
        auth_service.link_provider.assert_not_called()


def describe_disconnect_provider():
    def it_returns_204_when_disconnected(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.return_value = None

        response = client.delete("/api/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 204

    def it_returns_404_when_not_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.side_effect = AuthProviderNotLinkedError("not linked")

        response = client.delete("/api/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "AUTH_PROVIDER_NOT_LINKED"

    def it_returns_409_when_it_is_the_last_authentication_method(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.side_effect = LastAuthenticationMethodError("last one")

        response = client.delete("/api/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "LAST_AUTHENTICATION_METHOD"


def describe_update_profile():
    def it_returns_the_updated_profile(client: TestClient, user_service: AsyncMock):
        user_service.update_profile.return_value = UserModel(
            name="Alice Sparkle", username="new_alice", email="alice@example.com"
        )

        response = client.patch("/api/v1/users/me", json={"name": "Alice Sparkle", "username": "new_alice"})

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Alice Sparkle"
        assert body["username"] == "new_alice"

    def it_returns_409_when_the_username_is_taken(client: TestClient, user_service: AsyncMock):
        user_service.update_profile.side_effect = UsernameAlreadyExistsError("taken")

        response = client.patch("/api/v1/users/me", json={"username": "taken"})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "USERNAME_ALREADY_EXISTS"

    def it_returns_422_when_no_fields_are_provided(client: TestClient, user_service: AsyncMock):
        response = client.patch("/api/v1/users/me", json={})

        assert response.status_code == 422
        user_service.update_profile.assert_not_called()


def describe_change_password():
    def it_returns_a_fresh_token_pair_on_success(client: TestClient, auth_service: AsyncMock):
        auth_service.change_password.return_value = TokenResponse(
            access_token="new-access-token", refresh_token="new-refresh-token"
        )

        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "old-secret", "new_password": "new-secret-1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "new-access-token"
        assert body["refresh_token"] == "new-refresh-token"

    def it_returns_401_for_an_incorrect_current_password(client: TestClient, auth_service: AsyncMock):
        auth_service.change_password.side_effect = IncorrectPasswordError("wrong")

        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "wrong-secret", "new_password": "new-secret-1"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INCORRECT_PASSWORD"

    def it_returns_422_when_the_new_password_is_too_short(client: TestClient, auth_service: AsyncMock):
        response = client.put(
            "/api/v1/users/me/password",
            json={"current_password": "old-secret", "new_password": "short"},
        )

        assert response.status_code == 422
        auth_service.change_password.assert_not_called()

    def it_returns_200_when_setting_a_password_with_no_current_password(
        client: TestClient, auth_service: AsyncMock, current_user
    ):
        auth_service.change_password.return_value = TokenResponse(
            access_token="new-access-token", refresh_token="new-refresh-token"
        )

        response = client.put("/api/v1/users/me/password", json={"new_password": "new-secret-1"})

        assert response.status_code == 200
        auth_service.change_password.assert_awaited_once_with(current_user.id, None, "new-secret-1")


def describe_mark_book_read():
    def it_returns_204_on_success(client: TestClient, user_service: AsyncMock, book_repo: AsyncMock):
        book_repo.find_id_by_identifier.return_value = SOME_BOOK_ID

        response = client.put("/api/v1/users/me/read-books/google-books__ext-1")

        assert response.status_code == 204
        user_service.mark_book_read.assert_awaited_once()

    def it_returns_404_when_the_identifier_does_not_resolve_to_any_book(
        client: TestClient, user_service: AsyncMock, book_repo: AsyncMock
    ):
        book_repo.find_id_by_identifier.return_value = None

        response = client.put("/api/v1/users/me/read-books/google-books__missing")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"
        user_service.mark_book_read.assert_not_called()
