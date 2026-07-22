import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from canterlot.dto.auth import (
    AccessTokenResponse,
    ConnectedProvidersResponse,
    CreateSessionRequest,
    LinkProviderRequest,
    UserRegisterRequest,
)
from canterlot.models.user import LinkedProviderSchema, UserModel
from canterlot.types import AuthProviderName, SessionType

SOME_PASSWORD = SecretStr("Aa12345!")


def describe_username_normalization_and_constraints():
    def it_lowercases_the_username_on_the_request():
        request = UserRegisterRequest(
            name="Alice Smith",
            username="ALICE_1",
            email="a@b.com",
            password=SOME_PASSWORD,
            terms_version=1,
            privacy_version=1,
        )
        assert request.username == "alice_1"

    @pytest.mark.parametrize("bad_username", ["ab", "a" * 31])
    def it_rejects_usernames_outside_the_length_bounds(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(
                name="Alice Smith",
                username=bad_username,
                email="a@b.com",
                password=SOME_PASSWORD,
                terms_version=1,
                privacy_version=1,
            )

    @pytest.mark.parametrize("bad_username", ["has space", "has-dash", "has.dot", ""])
    def it_rejects_usernames_with_disallowed_characters(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(
                name="Alice Smith",
                username=bad_username,
                email="a@b.com",
                password=SOME_PASSWORD,
                terms_version=1,
                privacy_version=1,
            )


def describe_person_name_constraints():
    @pytest.mark.parametrize("bad_name", ["A", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(
                name=bad_name,
                username="alice_1",
                email="a@b.com",
                password=SOME_PASSWORD,
                terms_version=1,
                privacy_version=1,
            )


def describe_email_normalization():
    def it_normalizes_the_email_on_the_request():
        request = UserRegisterRequest(
            name="Alice Smith",
            username="alice_1",
            email="  Alice@Example.COM  ",
            password=SOME_PASSWORD,
            terms_version=1,
            privacy_version=1,
        )
        assert request.email == "alice@example.com"


def describe_create_session_request():
    def it_accepts_a_valid_password_session():
        request = CreateSessionRequest(type=SessionType.PASSWORD, username="alice_1", password=SOME_PASSWORD)
        assert request.username == "alice_1"

    def it_accepts_a_valid_oauth_session():
        request = CreateSessionRequest(
            type=SessionType.OAUTH, provider=AuthProviderName.GOOGLE, credential="some-id-token"
        )
        assert request.provider == AuthProviderName.GOOGLE

    def it_rejects_a_password_session_missing_the_password():
        with pytest.raises(ValidationError):
            CreateSessionRequest(type=SessionType.PASSWORD, username="alice_1")

    def it_rejects_a_password_session_missing_the_username():
        with pytest.raises(ValidationError):
            CreateSessionRequest(type=SessionType.PASSWORD, password=SOME_PASSWORD)

    def it_rejects_a_password_session_with_oauth_fields_set():
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                type=SessionType.PASSWORD,
                username="alice_1",
                password=SOME_PASSWORD,
                provider=AuthProviderName.GOOGLE,
            )

    def it_rejects_an_oauth_session_missing_the_credential():
        with pytest.raises(ValidationError):
            CreateSessionRequest(type=SessionType.OAUTH, provider=AuthProviderName.GOOGLE)

    def it_rejects_an_oauth_session_missing_the_provider():
        with pytest.raises(ValidationError):
            CreateSessionRequest(type=SessionType.OAUTH, credential="some-id-token")

    def it_rejects_an_oauth_session_with_password_fields_set():
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                type=SessionType.OAUTH,
                provider=AuthProviderName.GOOGLE,
                credential="some-id-token",
                username="alice_1",
            )

    def it_accepts_an_oauth_session_with_invite_context():
        request = CreateSessionRequest(
            type=SessionType.OAUTH,
            provider=AuthProviderName.GOOGLE,
            credential="some-id-token",
            invite_id="some-invite-id",
            invited_by="alice_1",
        )
        assert request.invite_id == "some-invite-id"
        assert request.invited_by == "alice_1"

    def it_rejects_a_password_session_with_invite_id_set():
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                type=SessionType.PASSWORD,
                username="alice_1",
                password=SOME_PASSWORD,
                invite_id="some-invite-id",
            )

    def it_rejects_a_password_session_with_invited_by_set():
        with pytest.raises(ValidationError):
            CreateSessionRequest(
                type=SessionType.PASSWORD,
                username="alice_1",
                password=SOME_PASSWORD,
                invited_by="bob_2",
            )


def describe_access_token_response():
    def it_defaults_the_token_type_to_bearer():
        response = AccessTokenResponse(access_token="access")
        assert response.token_type == "bearer"


def describe_link_provider_request():
    def it_defaults_redirect_uri_to_none():
        request = LinkProviderRequest(credential="some-credential")
        assert request.redirect_uri is None

    def it_accepts_a_redirect_uri():
        request = LinkProviderRequest(credential="some-code", redirect_uri="http://localhost:5173/callback")
        assert request.redirect_uri == "http://localhost:5173/callback"


def describe_connected_providers_response_from_model():
    def it_reports_no_password_and_an_empty_list_for_an_oauth_only_account():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = ConnectedProvidersResponse.from_model(user)

        assert response.has_password is False
        assert response.linked_providers == []

    def it_reports_the_password_flag_and_linked_providers():
        linked = LinkedProviderSchema(
            provider=AuthProviderName.GOOGLE, external_id="sub-1", picture_url=HttpUrl("https://example.com/pic.jpg")
        )
        user = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            hashed_password="hash",
            linked_providers=[linked],
        )

        response = ConnectedProvidersResponse.from_model(user)

        assert response.has_password is True
        assert response.linked_providers[0].provider == AuthProviderName.GOOGLE
        assert response.linked_providers[0].linked_at == linked.linked_at
        assert response.linked_providers[0].has_picture is True

    def it_reports_has_picture_false_when_the_linked_provider_has_no_picture():
        linked = LinkedProviderSchema(provider=AuthProviderName.GRAVATAR, external_id="wp-1", picture_url=None)
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com", linked_providers=[linked])

        response = ConnectedProvidersResponse.from_model(user)

        assert response.linked_providers[0].has_picture is False
