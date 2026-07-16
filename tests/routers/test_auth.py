from typing import cast
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from fastapi import FastAPI
from starlette.testclient import TestClient

from canterlot.dto.auth import TokenResponse
from canterlot.dto.invite import InvitePreviewResponse
from canterlot.exceptions import (
    ClubNotFoundError,
    GatewayConfigurationError,
    InvalidCredentialsError,
    InvalidInviteTokenError,
    InvalidOAuthCredentialError,
    InviteLinkDeactivatedError,
    OAuthLinkRequiredError,
)
from canterlot.models.enums import AuthOutcome, AuthProviderName, InviteType, JoinPolicy
from canterlot.routers.dependencies import get_optional_refresh_token_context
from canterlot.services.auth import OAuthSignInResult

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def _assert_refresh_cookie_set(response, expected_value: str):
    set_cookie = response.headers.get("set-cookie", "")
    assert f"refresh_token={expected_value}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "Path=/v1/auth" in set_cookie


def describe_create_session():
    def it_logs_in_with_a_password_session(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.return_value = TokenResponse(access_token="access", refresh_token="refresh")

        response = client.post(
            "/v1/auth/sessions",
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
            "/v1/auth/sessions",
            json={"type": "PASSWORD", "username": "alice_1", "password": "wrong"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_CREDENTIALS"

    def it_returns_422_for_a_password_session_missing_the_password(client: TestClient, auth_service: AsyncMock):
        response = client.post("/v1/auth/sessions", json={"type": "PASSWORD", "username": "alice_1"})

        assert response.status_code == 422
        auth_service.login_user.assert_not_called()

    def it_logs_in_via_oauth_when_the_identity_is_already_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.LOGGED_IN, access_token="access", refresh_token="refresh"
        )

        response = client.post(
            "/v1/auth/sessions",
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
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 201
        assert response.json()["access_token"] == "access"
        _assert_refresh_cookie_set(response, "refresh")

    def it_attributes_a_referral_when_a_new_oauth_account_resolves_an_inviter(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.CREATED, access_token="access", refresh_token="refresh"
        )
        invite_service.get_preview_metadata.return_value = InvitePreviewResponse(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.PUBLIC,
            invited_by_username="referrer_1",
        )

        response = client.post(
            "/v1/auth/sessions",
            json={
                "type": "OAUTH",
                "provider": "GOOGLE",
                "credential": "some-id-token",
                "invite_id": "some-invite-id",
            },
        )

        assert response.status_code == 201
        invite_service.get_preview_metadata.assert_awaited_once_with("some-invite-id", invited_by=None)
        auth_service.attribute_referral.assert_awaited_once_with("referrer_1")

    def it_does_not_attribute_a_referral_when_the_invite_has_no_resolvable_inviter(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.CREATED, access_token="access", refresh_token="refresh"
        )
        invite_service.get_preview_metadata.return_value = InvitePreviewResponse(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.PUBLIC,
            invited_by_username=None,
        )

        response = client.post(
            "/v1/auth/sessions",
            json={
                "type": "OAUTH",
                "provider": "GOOGLE",
                "credential": "some-id-token",
                "invite_id": "some-invite-id",
            },
        )

        assert response.status_code == 201
        auth_service.attribute_referral.assert_not_called()

    def it_does_not_resolve_an_invite_when_none_is_provided(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.CREATED, access_token="access", refresh_token="refresh"
        )

        response = client.post(
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 201
        invite_service.get_preview_metadata.assert_not_called()
        auth_service.attribute_referral.assert_not_called()

    def it_does_not_resolve_an_invite_for_an_existing_logged_in_oauth_account(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.LOGGED_IN, access_token="access", refresh_token="refresh"
        )

        response = client.post(
            "/v1/auth/sessions",
            json={
                "type": "OAUTH",
                "provider": "GOOGLE",
                "credential": "some-id-token",
                "invite_id": "some-invite-id",
            },
        )

        assert response.status_code == 200
        invite_service.get_preview_metadata.assert_not_called()
        auth_service.attribute_referral.assert_not_called()

    @pytest.mark.parametrize(
        "resolution_error",
        [InvalidInviteTokenError("nope"), InviteLinkDeactivatedError("expired"), ClubNotFoundError("gone")],
    )
    def it_still_creates_the_account_when_the_invite_cannot_be_resolved(
        client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock, resolution_error: Exception
    ):
        auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
            outcome=AuthOutcome.CREATED, access_token="access", refresh_token="refresh"
        )
        invite_service.get_preview_metadata.side_effect = resolution_error

        response = client.post(
            "/v1/auth/sessions",
            json={
                "type": "OAUTH",
                "provider": "GOOGLE",
                "credential": "some-id-token",
                "invite_id": "some-invite-id",
            },
        )

        assert response.status_code == 201
        assert response.json()["access_token"] == "access"
        auth_service.attribute_referral.assert_not_called()

    def it_returns_409_when_the_identity_requires_linking_to_an_existing_account(
        client: TestClient, auth_service: AsyncMock
    ):
        auth_service.sign_in_with_provider.side_effect = OAuthLinkRequiredError("linking required")

        response = client.post(
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OAUTH_LINK_REQUIRED"
        assert "set-cookie" not in response.headers

    def it_returns_401_for_an_invalid_oauth_credential(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.side_effect = InvalidOAuthCredentialError("bad token")

        response = client.post(
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "garbage"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_OAUTH_CREDENTIAL"

    def it_returns_503_when_the_oauth_provider_is_not_configured(client: TestClient, auth_service: AsyncMock):
        auth_service.sign_in_with_provider.side_effect = GatewayConfigurationError("disabled")

        response = client.post(
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "GOOGLE", "credential": "some-id-token"},
        )

        assert response.status_code == 503
        assert response.json()["error"]["error_code"] == "GATEWAY_CONFIGURATION_ERROR"

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, auth_service: AsyncMock):
        response = client.post(
            "/v1/auth/sessions",
            json={"type": "OAUTH", "provider": "FACEBOOK", "credential": "some-id-token"},
        )

        assert response.status_code == 422
        auth_service.sign_in_with_provider.assert_not_called()

    def it_returns_422_for_an_oauth_session_missing_the_credential(client: TestClient, auth_service: AsyncMock):
        response = client.post(
            "/v1/auth/sessions",
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

        response = client.post("/v1/auth/login", data={"username": "alice_1", "password": "secret1"})

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "refresh")

    def it_returns_401_for_invalid_credentials(client: TestClient, auth_service: AsyncMock):
        auth_service.login_user.side_effect = InvalidCredentialsError("nope")

        response = client.post("/v1/auth/login", data={"username": "alice_1", "password": "wrong"})

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INVALID_CREDENTIALS"


def describe_rotate_session():
    def it_returns_a_rotated_access_token_and_sets_a_new_refresh_cookie(client: TestClient, auth_service: AsyncMock):
        auth_service.rotate_refresh_token.return_value = TokenResponse(
            access_token="new-access", refresh_token="new-refresh"
        )

        response = client.put("/v1/auth/sessions/current")

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "new-access"
        assert "refresh_token" not in body
        _assert_refresh_cookie_set(response, "new-refresh")
        auth_service.rotate_refresh_token.assert_awaited_once_with(SOME_USER_ID, "old-refresh-token")


def describe_logout():
    def it_logs_out_the_current_session_and_clears_the_cookie(client: TestClient, auth_service: AsyncMock):
        response = client.delete("/v1/auth/sessions/current")

        assert response.status_code == 204
        auth_service.logout.assert_awaited_once_with(SOME_USER_ID, "old-refresh-token")
        set_cookie = response.headers.get("set-cookie", "")
        assert 'refresh_token=""' in set_cookie
        assert "Max-Age=0" in set_cookie

    def it_is_a_no_op_when_there_is_no_session_cookie(client: TestClient, auth_service: AsyncMock):
        cast(FastAPI, client.app).dependency_overrides[get_optional_refresh_token_context] = lambda: None

        response = client.delete("/v1/auth/sessions/current")

        assert response.status_code == 204
        auth_service.logout.assert_not_called()
