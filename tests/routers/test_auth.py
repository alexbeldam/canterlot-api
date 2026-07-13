from typing import cast
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from fastapi import FastAPI
from starlette.testclient import TestClient

from canterlot.dto.auth import TokenResponse
from canterlot.exceptions import (
    GatewayConfigurationError,
    InvalidCredentialsError,
    InvalidOAuthCredentialError,
    OAuthLinkRequiredError,
)
from canterlot.models.enums import AuthOutcome, AuthProviderName
from canterlot.routers.dependencies import get_optional_refresh_token_context
from canterlot.services.auth import OAuthSignInResult

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def _assert_refresh_cookie_set(response, expected_value: str):
    set_cookie = response.headers.get("set-cookie", "")
    assert f"refresh_token={expected_value}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "Path=/api/v1/auth" in set_cookie


def describe_create_session():
    def it_logs_in_with_a_password_session(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.return_value = TokenResponse(access_token="access", refresh_token="refresh")

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "PASSWORD", "username": "alice_1", "password": "secret1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "refresh")
        auth_service.login_user.assert_awaited_once_with(username="alice_1", plain_password="secret1")

    def it_returns_401_for_invalid_password_credentials(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.side_effect = InvalidCredentialsError("nope")

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "PASSWORD", "username": "alice_1", "password": "wrong"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_CREDENTIALS"

    def it_returns_422_for_a_password_session_missing_the_password(client: TestClient, auth_service: AsyncMock):
        response = client.post("/api/v1/auth/sessions", json={"type": "PASSWORD", "username": "alice_1"})

        assert response.status_code == 422
        auth_service.login_user.assert_not_called()

    def it_logs_in_via_oauth_when_the_identity_is_already_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.LOGGED_IN, access_token="access", refresh_token="refresh"
        )

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "refresh")
        auth_service.sign_in_with_provider.assert_awaited_once_with(AuthProviderName.GOOGLE, "some-id-token")

    def it_returns_created_for_a_brand_new_oauth_account(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.CREATED, access_token="access", refresh_token="refresh"
        )

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 201
        assert response.json()["access_token"] == "access"
        _assert_refresh_cookie_set(response, "refresh")

    def it_returns_409_when_the_identity_requires_linking_to_an_existing_account(
        client: TestClient, auth_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.side_effect = OAuthLinkRequiredError("linking required")

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OAUTH_LINK_REQUIRED"
        assert "set-cookie" not in response.headers

    def it_returns_401_for_an_invalid_oauth_credential(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.side_effect = InvalidOAuthCredentialError("bad token")

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "garbage"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_OAUTH_CREDENTIAL"

    def it_returns_503_when_the_oauth_provider_is_not_configured(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.side_effect = GatewayConfigurationError("disabled")

        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 503
        assert response.json()["error"]["error_code"] == "GATEWAY_CONFIGURATION_ERROR"

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, auth_service: AsyncMock):
        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "FACEBOOK", "credential": "some-id-token"},
        )

        assert response.status_code == 422
        auth_service.sign_in_with_provider.assert_not_called()

    def it_returns_422_for_an_oauth_session_missing_the_credential(client: TestClient, auth_service: AsyncMock):
        response = client.post(
            "/api/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE"},
        )

        assert response.status_code == 422
        auth_service.sign_in_with_provider.assert_not_called()


def describe_login_swagger_shim():
    def it_is_hidden_from_the_openapi_schema(client: TestClient):
        schema = client.get("/openapi.json").json()

        assert "/auth/login" not in schema["paths"]

    def it_still_logs_in_via_the_form_encoded_oauth2_password_flow(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.return_value = TokenResponse(access_token="access", refresh_token="refresh")

        response = client.post("/api/v1/auth/login", data={"username": "alice_1", "password": "secret1"})

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "refresh")

    def it_returns_401_for_invalid_credentials(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.side_effect = InvalidCredentialsError("nope")

        response = client.post("/api/v1/auth/login", data={"username": "alice_1", "password": "wrong"})

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_CREDENTIALS"


def describe_rotate_session():
    def it_returns_a_rotated_access_token_and_sets_a_new_refresh_cookie(client: TestClient, auth_service: AsyncMock):
        auth_service.rotate_refresh_token.return_value = TokenResponse(
            access_token="new-access", refresh_token="new-refresh"
        )

        response = client.put("/api/v1/auth/sessions/current")

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "new-access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "new-refresh")
        auth_service.rotate_refresh_token.assert_awaited_once_with(SOME_USER_ID, "old-refresh-token")


def describe_logout():
    def it_logs_out_the_current_session_and_clears_the_cookie(client: TestClient, auth_service: AsyncMock):
        response = client.delete("/api/v1/auth/sessions/current")

        assert response.status_code == 204
        auth_service.logout.assert_awaited_once_with(SOME_USER_ID, "old-refresh-token")
        set_cookie = response.headers.get("set-cookie", "")
        assert 'refresh_token=""' in set_cookie
        assert "Max-Age=0" in set_cookie

    def it_is_a_no_op_when_there_is_no_session_cookie(client: TestClient, auth_service: AsyncMock):
        cast(FastAPI, client.app).dependency_overrides[get_optional_refresh_token_context] = lambda: None

        response = client.delete("/api/v1/auth/sessions/current")

        assert response.status_code == 204
        auth_service.logout.assert_not_called()
