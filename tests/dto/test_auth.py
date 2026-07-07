import pytest
from pydantic import ValidationError

from canterlot.dto.auth import ConnectedProvidersResponse, OAuthSignInResponse, UserRegisterRequest
from canterlot.models.enums import AuthOutcome, AuthProviderName
from canterlot.models.user import LinkedProviderSchema, UserModel


def describe_username_normalization_and_constraints():
    def it_lowercases_the_username_on_the_request():
        request = UserRegisterRequest(name="Alice Smith", username="ALICE_1", email="a@b.com", password="secret1")
        assert request.username == "alice_1"

    @pytest.mark.parametrize("bad_username", ["ab", "a" * 31])
    def it_rejects_usernames_outside_the_length_bounds(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username=bad_username, email="a@b.com", password="secret1")

    @pytest.mark.parametrize("bad_username", ["has space", "has-dash", "has.dot", ""])
    def it_rejects_usernames_with_disallowed_characters(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username=bad_username, email="a@b.com", password="secret1")


def describe_person_name_constraints():
    @pytest.mark.parametrize("bad_name", ["A", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name=bad_name, username="alice_1", email="a@b.com", password="secret1")


def describe_email_normalization():
    def it_normalizes_the_email_on_the_request():
        request = UserRegisterRequest(
            name="Alice Smith", username="alice_1", email="  Alice@Example.COM  ", password="secret1"
        )
        assert request.email == "alice@example.com"


def describe_password_constraints():
    def it_rejects_passwords_shorter_than_six_characters():
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username="alice_1", email="a@b.com", password="short")

    def it_accepts_a_password_at_the_minimum_length():
        request = UserRegisterRequest(name="Alice Smith", username="alice_1", email="a@b.com", password="123456")
        assert request.password == "123456"


def describe_oauth_sign_in_response():
    def it_carries_no_tokens_by_default():
        response = OAuthSignInResponse(outcome=AuthOutcome.LINK_REQUIRED)
        assert response.access_token is None
        assert response.refresh_token is None


def describe_connected_providers_response_from_model():
    def it_reports_no_password_and_an_empty_list_for_an_oauth_only_account():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = ConnectedProvidersResponse.from_model(user)

        assert response.has_password is False
        assert response.linked_providers == []

    def it_reports_the_password_flag_and_linked_providers():
        linked = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1")
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
