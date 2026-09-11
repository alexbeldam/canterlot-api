from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl, ValidationError

from canterlot.config import get_settings
from canterlot.dto.book import RatedBook
from canterlot.dto.user import (
    AvatarDTO,
    MarkBookReadRequest,
    ReadBookSummaryDTO,
    SetAvatarRequest,
    UserProfileResponse,
)
from canterlot.models.user import AvatarSchema
from canterlot.types import AuthProviderName, BadgeReason
from tools.factories import BookFactory, UpdateProfileRequestFactory, UserFactory


def describe_update_profile_request():
    def it_rejects_a_request_with_no_fields_provided():
        with pytest.raises(ValidationError):
            UpdateProfileRequestFactory.build(name=None, username=None)

    def it_accepts_only_a_name():
        request = UpdateProfileRequestFactory.build(name="Alice Smith", username=None)
        assert request.name == "Alice Smith"
        assert request.username is None

    def it_accepts_only_a_username():
        request = UpdateProfileRequestFactory.build(name=None, username="ALICE_1")
        assert request.username == "alice_1"
        assert request.name is None

    def it_lowercases_the_username_when_provided():
        request = UpdateProfileRequestFactory.build(username="ALICE_1")
        assert request.username == "alice_1"

    @pytest.mark.parametrize("bad_username", ["ab", "a" * 31, "has space", "has-dash"])
    def it_rejects_a_username_outside_constraints(bad_username: str):
        with pytest.raises(ValidationError):
            UpdateProfileRequestFactory.build(username=bad_username)

    @pytest.mark.parametrize("bad_name", ["A", "a" * 51, "  "])
    def it_rejects_a_name_outside_constraints(bad_name: str):
        with pytest.raises(ValidationError):
            UpdateProfileRequestFactory.build(name=bad_name)


def describe_mark_book_read_request():
    def it_defaults_rating_to_none():
        request = MarkBookReadRequest()
        assert request.rating is None

    @pytest.mark.parametrize("rating", [0.5, 1.0, 2.5, 5.0])
    def it_accepts_half_step_ratings_within_bounds(rating: float):
        request = MarkBookReadRequest(rating=rating)
        assert request.rating == rating

    @pytest.mark.parametrize("rating", [0.0, 0.4, 5.5])
    def it_rejects_ratings_outside_bounds(rating: float):
        with pytest.raises(ValidationError):
            MarkBookReadRequest(rating=rating)

    def it_rejects_a_rating_not_on_a_half_step():
        with pytest.raises(ValidationError):
            MarkBookReadRequest(rating=1.2)


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
        user = UserFactory.build(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert response.name == "Alice Smith"
        assert response.username == "alice_1"
        assert response.email == "a@b.com"
        assert response.avatar is None
        assert response.generated_avatar_seed == user.generated_avatar_seed

    def it_reflects_the_users_avatar_when_set():
        user = UserFactory.build(
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
        user = UserFactory.build(name="Alice Smith", username="alice_1", email="a@b.com")

        response = UserProfileResponse.from_model(user)

        assert len(response.badges) == 1
        assert response.badges[0].reason == BadgeReason.JOINED

    def it_needs_profile_completion_and_reacceptance_for_a_brand_new_account():
        user = UserFactory.build(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            accepted_terms_version=0,
            accepted_privacy_version=0,
            profile_completed_at=None,
        )

        response = UserProfileResponse.from_model(user)

        assert response.needs_profile_completion is True
        assert response.needs_terms_reacceptance is True
        assert response.needs_privacy_reacceptance is True

    def it_needs_nothing_once_fully_accepted_at_the_current_version():
        settings = get_settings().auth
        user = UserFactory.build(
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
        settings = get_settings().auth
        user = UserFactory.build(
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


def describe_read_book_summary_dto():
    def it_reflects_the_book_rating_and_read_at():
        book = BookFactory.build()
        read_at = datetime(2025, 6, 1, tzinfo=UTC)

        summary = ReadBookSummaryDTO.from_model(RatedBook(book=book, rating=4.5, read_at=read_at))

        assert summary.external_id == book.external_id
        assert summary.title == book.title
        assert summary.rating == 4.5
        assert summary.read_at == read_at

    def it_allows_a_null_rating_for_an_unrated_read_book():
        book = BookFactory.build()
        read_at = datetime(2025, 6, 1, tzinfo=UTC)

        summary = ReadBookSummaryDTO.from_model(RatedBook(book=book, rating=None, read_at=read_at))

        assert summary.rating is None
