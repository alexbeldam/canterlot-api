from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl, ValidationError

from canterlot.config import get_settings
from canterlot.dto.user import (
    AvatarDTO,
    ChangePasswordRequest,
    SetAvatarRequest,
    UpdateProfileRequest,
    UserProfileResponse,
)
from canterlot.models.user import AvatarSchema, UserModel
from canterlot.types import AuthProviderName, BadgeReason


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


def describe_avatar_dto():
    def it_reflects_source_and_value_from_the_model():
        avatar = AvatarSchema(source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/somehash"))

        dto = AvatarDTO.from_model(avatar)

        assert dto.source == AuthProviderName.GRAVATAR
        assert str(dto.value) == "https://gravatar.com/avatar/somehash"


def describe_set_avatar_request():
    @pytest.mark.parametrize("source", [AuthProviderName.GOOGLE, AuthProviderName.GRAVATAR])
    def it_accepts_each_recognized_source(source: AuthProviderName):
        request = SetAvatarRequest(source=source)
        assert request.source == source

    def it_rejects_an_unrecognized_source():
        with pytest.raises(ValidationError):
            SetAvatarRequest.model_validate({"source": "NOT_A_SOURCE"})


def describe_user_profile_response_from_model():
    def it_reflects_the_users_name_username_and_email():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert response.name == "Alice Smith"
        assert response.username == "alice_1"
        assert response.email == "a@b.com"
        assert response.avatar is None
        assert response.generated_avatar_seed == user.generated_avatar_seed

    def it_reflects_the_users_avatar_when_set():
        user = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=HttpUrl("https://example.com/pic.jpg")),
        )

        response = UserProfileResponse.from_model(user)

        assert response.avatar is not None
        assert response.avatar.source == AuthProviderName.GOOGLE
        assert str(response.avatar.value) == "https://example.com/pic.jpg"

    def it_reflects_the_users_earned_badges():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert len(response.badges) == 1
        assert response.badges[0].reason == BadgeReason.JOINED

    def it_needs_profile_completion_and_reacceptance_for_a_brand_new_account():
        user = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert response.needs_profile_completion is True
        assert response.needs_terms_reacceptance is True
        assert response.needs_privacy_reacceptance is True

    def it_needs_nothing_once_fully_accepted_at_the_current_version():
        settings = get_settings()
        user = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            accepted_terms_version=settings.current_terms_version,
            accepted_terms_at=datetime.now(UTC),
            accepted_privacy_version=settings.current_privacy_version,
            accepted_privacy_at=datetime.now(UTC),
            profile_completed_at=datetime.now(UTC),
        )

        response = UserProfileResponse.from_model(user)

        assert response.needs_profile_completion is False
        assert response.needs_terms_reacceptance is False
        assert response.needs_privacy_reacceptance is False

    def it_needs_reacceptance_when_the_accepted_version_is_behind_current():
        settings = get_settings()
        user = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            accepted_terms_version=settings.current_terms_version - 1,
            accepted_terms_at=datetime.now(UTC),
            accepted_privacy_version=settings.current_privacy_version,
            accepted_privacy_at=datetime.now(UTC),
            profile_completed_at=datetime.now(UTC),
        )

        response = UserProfileResponse.from_model(user)

        assert response.needs_terms_reacceptance is True
        assert response.needs_privacy_reacceptance is False


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
