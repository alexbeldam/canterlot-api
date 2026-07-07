from datetime import UTC, datetime
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.dto.auth import ConnectedProvidersResponse, LinkedProviderDTO
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    GatewayConfigurationError,
    InvalidOAuthCredentialError,
    LastAuthenticationMethodError,
)
from canterlot.models.enums import AuthProviderName


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
