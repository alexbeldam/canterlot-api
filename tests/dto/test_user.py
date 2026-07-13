import pytest
from pydantic import ValidationError

from canterlot.dto.user import ChangePasswordRequest, UpdateProfileRequest, UserProfileResponse
from canterlot.models.user import UserModel


def describe_update_profile_request():
    def it_rejects_a_request_with_no_fields_provided():
        with pytest.raises(ValidationError):
            UpdateProfileRequest()

    def it_accepts_only_a_name():
        request = UpdateProfileRequest(name="Alice Smith")
        assert request.name == "Alice Smith"
        assert request.username is None

    def it_accepts_only_a_username():
        request = UpdateProfileRequest(username="ALICE_1")
        assert request.username == "alice_1"
        assert request.name is None

    def it_lowercases_the_username_when_provided():
        request = UpdateProfileRequest(username="ALICE_1")
        assert request.username == "alice_1"

    @pytest.mark.parametrize("bad_username", ["ab", "a" * 31, "has space", "has-dash"])
    def it_rejects_a_username_outside_constraints(bad_username: str):
        with pytest.raises(ValidationError):
            UpdateProfileRequest(username=bad_username)

    @pytest.mark.parametrize("bad_name", ["A", "a" * 51, "  "])
    def it_rejects_a_name_outside_constraints(bad_name: str):
        with pytest.raises(ValidationError):
            UpdateProfileRequest(name=bad_name)


def describe_user_profile_response_from_model():
    def it_reflects_the_users_name_and_username():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert response.name == "Alice Smith"
        assert response.username == "alice_1"


def describe_change_password_request():
    def it_rejects_a_new_password_shorter_than_six_characters():
        with pytest.raises(ValidationError):
            ChangePasswordRequest(current_password="whatever", new_password="short")

    def it_accepts_a_new_password_at_the_minimum_length():
        request = ChangePasswordRequest(current_password="whatever", new_password="123456")
        assert request.new_password == "123456"

    def it_allows_omitting_the_current_password():
        request = ChangePasswordRequest(new_password="123456")
        assert request.current_password is None
