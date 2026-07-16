from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from pydantic import HttpUrl
from starlette.testclient import TestClient

from canterlot.dto.auth import ConnectedProvidersResponse, LinkedProviderDTO, TokenResponse
from canterlot.dto.club import ClubOnboarding
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidOAuthCredentialError,
    LastAuthenticationMethodError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.models.enums import AuthProviderName, ClubOnboardingStatus
from canterlot.models.user import AvatarSchema, UserModel
from canterlot.services.auth import RegisterResult
from canterlot.services.invite import InviteValidationResult

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _register_payload(**overrides) -> dict:
    defaults = {
        "name": "Alice Smith",
        "username": "alice_1",
        "email": "alice@example.com",
        "password": "secret1",
        "terms_version": 1,
        "privacy_version": 1,
    }
    return {**defaults, **overrides}


def describe_register():
    def it_registers_a_user_without_an_invite(client: TestClient, auth_service: AsyncMock, invite_service: AsyncMock):
        auth_service.register_user.return_value = RegisterResult(
            access_token="access", refresh_token="refresh", user_id=SOME_USER_ID
        )

        response = client.post("/v1/users", json=_register_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["access_token"] == "access"
        assert "refresh_token" not in body
        assert body["onboarding"] is None
        assert response.headers["Location"] == "/v1/users/me"
        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=refresh" in set_cookie
        assert "HttpOnly" in set_cookie
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

        response = client.post("/v1/users", json=_register_payload(invite_id="some-invite-id"))

        assert response.status_code == 201
        assert response.json()["onboarding"]["status"] == "JOINED"
        invite_service.register_invite_usage.assert_awaited_once_with("some-invite-id")

    def it_returns_409_when_the_username_is_taken(client: TestClient, auth_service: AsyncMock):
        auth_service.register_user.side_effect = UsernameAlreadyExistsError("taken")

        response = client.post("/v1/users", json=_register_payload())

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "USERNAME_ALREADY_EXISTS"

    def it_returns_422_for_a_password_that_is_too_short(client: TestClient, auth_service: AsyncMock):
        response = client.post("/v1/users", json=_register_payload(password="short"))

        assert response.status_code == 422
        auth_service.register_user.assert_not_called()

    def it_returns_409_when_the_legal_version_is_stale(client: TestClient, auth_service: AsyncMock):
        auth_service.register_user.side_effect = StaleLegalVersionError("stale")

        response = client.post("/v1/users", json=_register_payload(terms_version=0))

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "STALE_LEGAL_VERSION"


def describe_get_connected_providers():
    def it_returns_the_connected_providers(client: TestClient, auth_service: AsyncMock):
        auth_service.list_connected_providers.return_value = ConnectedProvidersResponse(
            has_password=True,
            linked_providers=[
                LinkedProviderDTO(provider=AuthProviderName.GOOGLE, linked_at=datetime.now(UTC), has_picture=True)
            ],
        )

        response = client.get("/v1/users/me/auth-providers")

        assert response.status_code == 200
        body = response.json()
        assert body["has_password"] is True
        assert body["linked_providers"][0]["provider"] == "GOOGLE"
        assert body["linked_providers"][0]["has_picture"] is True


def describe_link_provider():
    def it_returns_204_when_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.return_value = None

        response = client.post("/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 204

    def it_returns_401_for_an_invalid_credential(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = InvalidOAuthCredentialError("bad token")

        response = client.post("/v1/users/me/auth-providers/GOOGLE", json={"credential": "garbage"})

        assert response.status_code == 401

    def it_returns_409_when_already_linked_to_a_different_account(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = AuthProviderAlreadyLinkedError("taken")

        response = client.post("/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "AUTH_PROVIDER_ALREADY_LINKED"

    def it_returns_503_when_the_provider_is_not_configured(client: TestClient, auth_service: AsyncMock):
        auth_service.link_provider.side_effect = GatewayConfigurationError("disabled")

        response = client.post("/v1/users/me/auth-providers/GOOGLE", json={"credential": "some-id-token"})

        assert response.status_code == 503

    def it_returns_422_for_an_unrecognized_provider(client: TestClient, auth_service: AsyncMock):
        response = client.post("/v1/users/me/auth-providers/FACEBOOK", json={"credential": "some-id-token"})

        assert response.status_code == 422
        auth_service.link_provider.assert_not_called()


def describe_disconnect_provider():
    def it_returns_204_when_disconnected(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.return_value = None

        response = client.delete("/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 204

    def it_returns_404_when_not_linked(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.side_effect = AuthProviderNotLinkedError("not linked")

        response = client.delete("/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "AUTH_PROVIDER_NOT_LINKED"

    def it_returns_409_when_it_is_the_last_authentication_method(client: TestClient, auth_service: AsyncMock):
        auth_service.disconnect_provider.side_effect = LastAuthenticationMethodError("last one")

        response = client.delete("/v1/users/me/auth-providers/GOOGLE")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "LAST_AUTHENTICATION_METHOD"


def describe_get_own_profile():
    def it_returns_the_callers_profile_with_no_active_provider_avatar(client: TestClient, user_service: AsyncMock):
        user_service.get_profile.return_value = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="alice@example.com",
            generated_avatar_seed="some-seed",
        )

        response = client.get("/v1/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Alice Smith"
        assert body["username"] == "alice_1"
        assert body["email"] == "alice@example.com"
        assert body["avatar"] is None
        assert body["generated_avatar_seed"] == "some-seed"

    def it_returns_the_active_provider_avatar_when_set(client: TestClient, user_service: AsyncMock):
        user_service.get_profile.return_value = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="alice@example.com",
            avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=HttpUrl("https://example.com/pic.jpg")),
        )

        response = client.get("/v1/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["avatar"] == {"source": "GOOGLE", "value": "https://example.com/pic.jpg"}


def describe_update_profile():
    def it_returns_the_updated_profile(client: TestClient, user_service: AsyncMock):
        user_service.update_profile.return_value = UserModel(
            name="Alice Sparkle", username="new_alice", email="alice@example.com"
        )

        response = client.patch("/v1/users/me", json={"name": "Alice Sparkle", "username": "new_alice"})

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Alice Sparkle"
        assert body["username"] == "new_alice"

    def it_returns_409_when_the_username_is_taken(client: TestClient, user_service: AsyncMock):
        user_service.update_profile.side_effect = UsernameAlreadyExistsError("taken")

        response = client.patch("/v1/users/me", json={"username": "taken"})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "USERNAME_ALREADY_EXISTS"

    def it_returns_422_when_no_fields_are_provided(client: TestClient, user_service: AsyncMock):
        response = client.patch("/v1/users/me", json={})

        assert response.status_code == 422
        user_service.update_profile.assert_not_called()


def describe_change_password():
    def it_returns_a_fresh_access_token_and_sets_a_refresh_cookie_on_success(
        client: TestClient, auth_service: AsyncMock
    ):
        auth_service.change_password.return_value = TokenResponse(
            access_token="new-access-token", refresh_token="new-refresh-token"
        )

        response = client.put(
            "/v1/users/me/password",
            json={"current_password": "old-secret", "new_password": "new-secret-1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "new-access-token"
        assert "refresh_token" not in body
        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=new-refresh-token" in set_cookie
        assert "HttpOnly" in set_cookie

    def it_returns_401_for_an_incorrect_current_password(client: TestClient, auth_service: AsyncMock):
        auth_service.change_password.side_effect = IncorrectPasswordError("wrong")

        response = client.put(
            "/v1/users/me/password",
            json={"current_password": "wrong-secret", "new_password": "new-secret-1"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["error_code"] == "INCORRECT_PASSWORD"

    def it_returns_422_when_the_new_password_is_too_short(client: TestClient, auth_service: AsyncMock):
        response = client.put(
            "/v1/users/me/password",
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

        response = client.put("/v1/users/me/password", json={"new_password": "new-secret-1"})

        assert response.status_code == 200
        auth_service.change_password.assert_awaited_once_with(current_user.id, None, "new-secret-1")


def describe_set_avatar():
    def it_returns_the_updated_profile(client: TestClient, user_service: AsyncMock):
        user_service.set_avatar_source.return_value = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="alice@example.com",
            avatar=AvatarSchema(
                source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/somehash")
            ),
        )

        response = client.put("/v1/users/me/avatar", json={"source": "GRAVATAR"})

        assert response.status_code == 200
        body = response.json()
        assert body["avatar"] == {"source": "GRAVATAR", "value": "https://gravatar.com/avatar/somehash"}
        user_service.set_avatar_source.assert_awaited_once()

    def it_returns_404_when_google_is_not_linked(client: TestClient, user_service: AsyncMock):
        user_service.set_avatar_source.side_effect = AuthProviderNotLinkedError("not linked")

        response = client.put("/v1/users/me/avatar", json={"source": "GOOGLE"})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "AUTH_PROVIDER_NOT_LINKED"

    def it_returns_422_for_an_unrecognized_source(client: TestClient, user_service: AsyncMock):
        response = client.put("/v1/users/me/avatar", json={"source": "UPLOAD"})

        assert response.status_code == 422
        user_service.set_avatar_source.assert_not_called()


def describe_clear_avatar():
    def it_returns_204_on_success(client: TestClient, user_service: AsyncMock):
        user_service.clear_avatar.return_value = UserModel(
            name="Alice Smith", username="alice_1", email="alice@example.com"
        )

        response = client.delete("/v1/users/me/avatar")

        assert response.status_code == 204
        user_service.clear_avatar.assert_awaited_once()


def describe_regenerate_avatar_seed():
    def it_returns_the_updated_profile(client: TestClient, user_service: AsyncMock):
        user_service.regenerate_avatar_seed.return_value = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="alice@example.com",
            generated_avatar_seed="fresh-seed",
        )

        response = client.post("/v1/users/me/avatar/seed")

        assert response.status_code == 200
        body = response.json()
        assert body["generated_avatar_seed"] == "fresh-seed"
        user_service.regenerate_avatar_seed.assert_awaited_once()


def describe_accept_legal_documents():
    def it_returns_the_updated_profile(client: TestClient, user_service: AsyncMock):
        user_service.accept_legal_documents.return_value = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="alice@example.com",
            accepted_terms_version=1,
            accepted_privacy_version=1,
            profile_completed_at=datetime.now(UTC),
        )

        response = client.post("/v1/users/me/legal-acceptance", json={"terms_version": 1, "privacy_version": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["needs_profile_completion"] is False
        assert body["needs_terms_reacceptance"] is False
        assert body["needs_privacy_reacceptance"] is False
        user_service.accept_legal_documents.assert_awaited_once_with(SOME_USER_ID, terms_version=1, privacy_version=1)

    def it_returns_409_when_the_submitted_version_is_stale(client: TestClient, user_service: AsyncMock):
        user_service.accept_legal_documents.side_effect = StaleLegalVersionError("stale")

        response = client.post("/v1/users/me/legal-acceptance", json={"terms_version": 0, "privacy_version": 1})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "STALE_LEGAL_VERSION"

    def it_returns_422_when_a_version_is_missing(client: TestClient, user_service: AsyncMock):
        response = client.post("/v1/users/me/legal-acceptance", json={"terms_version": 1})

        assert response.status_code == 422
        user_service.accept_legal_documents.assert_not_called()


def describe_mark_book_read():
    def it_returns_204_on_success(client: TestClient, user_service: AsyncMock, book_repo: AsyncMock):
        book_repo.find_id_by_identifier.return_value = SOME_BOOK_ID

        response = client.put("/v1/users/me/read-books/google-books__ext-1")

        assert response.status_code == 204
        user_service.mark_book_read.assert_awaited_once()

    def it_returns_404_when_the_identifier_does_not_resolve_to_any_book(
        client: TestClient, user_service: AsyncMock, book_repo: AsyncMock
    ):
        book_repo.find_id_by_identifier.return_value = None

        response = client.put("/v1/users/me/read-books/google-books__missing")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "BOOK_NOT_FOUND"
        user_service.mark_book_read.assert_not_called()
