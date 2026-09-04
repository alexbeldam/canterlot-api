import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from pydantic import HttpUrl

from canterlot.emails.core.enums import EmailCategory
from canterlot.exceptions import (
    AuthProviderNotLinkedError,
    InvalidCredentialsError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.exceptions.user import UserNotFoundError
from canterlot.models.book import ReadBook
from canterlot.models.user import EmailPreferencesSchema, LinkedProviderSchema
from canterlot.services.user import UserService
from canterlot.types import AuthProviderName
from canterlot.utils.security import UnsubscribeScope, UnsubscribeTokenData
from tools.factories import UserFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439013")


@pytest.fixture
def service(user_repo: AsyncMock, cache_repo: AsyncMock) -> UserService:
    return UserService(user_repo=user_repo, cache_repo=cache_repo)


def describe_get_by_username():
    async def it_returns_user_when_found(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_username.return_value = UserFactory.build(username="alice_1")

        user = await service.get_by_username("alice_1")

        assert user.username == "alice_1"
        user_repo.find_by_username.assert_awaited_once_with("alice_1")

    async def it_raises_user_not_found_error_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_username.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.get_by_username("missing_user")


def describe_marking_a_book_as_read():
    async def it_appends_the_book_to_the_users_reading_history(service: UserService, user_repo: AsyncMock):
        await service.mark_book_read(user_id=SOME_USER_ID, book_id=SOME_BOOK_ID)

        user_repo.push_read_book_by_id.assert_awaited_once()
        call_kwargs = user_repo.push_read_book_by_id.call_args.kwargs
        assert call_kwargs["user_id"] == SOME_USER_ID
        assert isinstance(call_kwargs["read_book"], ReadBook)
        assert call_kwargs["read_book"].id == SOME_BOOK_ID


def describe_update_profile():
    async def it_updates_both_fields(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(id=SOME_USER_ID)
        user_repo.exists_by_username.return_value = False
        user_repo.update_profile.return_value = True

        updated = await service.update_profile(user, name="Alice Sparkle", username="new_alice")

        assert updated.name == "Alice Sparkle"
        assert updated.username == "new_alice"
        user_repo.update_profile.assert_awaited_once_with(SOME_USER_ID, name="Alice Sparkle", username="new_alice")

    async def it_updates_only_the_provided_field(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(id=SOME_USER_ID, username="alice_1")
        user_repo.update_profile.return_value = True

        updated = await service.update_profile(user, name="Alice Sparkle", username=None)

        assert updated.name == "Alice Sparkle"
        assert updated.username == "alice_1"
        user_repo.exists_by_username.assert_not_called()

    async def it_allows_resubmitting_the_users_own_current_username(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(id=SOME_USER_ID, username="alice_1")
        user_repo.update_profile.return_value = True

        await service.update_profile(user, name=None, username="alice_1")

        user_repo.exists_by_username.assert_not_called()

    async def it_rejects_a_username_already_taken_by_someone_else(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()
        user_repo.exists_by_username.return_value = True

        with pytest.raises(UsernameAlreadyExistsError):
            await service.update_profile(user, name=None, username="taken")

        user_repo.update_profile.assert_not_called()

    async def it_raises_when_the_user_vanishes_between_read_and_write(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()
        user_repo.update_profile.return_value = False

        with pytest.raises(InvalidCredentialsError):
            await service.update_profile(user, name="Alice Sparkle", username=None)


def describe_find_profile_by_id():
    async def it_returns_the_user_when_found(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_id.return_value = UserFactory.build(id=SOME_USER_ID, username="alice_1")

        user = await service.get_by_id(SOME_USER_ID)

        assert user is not None
        assert user.username == "alice_1"

    async def it_raises_user_not_found_error_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.get_by_id(SOME_USER_ID)


def describe_set_avatar_source():
    async def it_uses_the_linked_google_picture(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GOOGLE,
                    external_id="sub-1",
                    picture_url=HttpUrl("https://example.com/pic.jpg"),
                )
            ]
        )
        user_repo.set_avatar.return_value = True

        updated = await service.set_avatar_source(user, AuthProviderName.GOOGLE)

        assert updated.avatar is not None
        assert updated.avatar.source == AuthProviderName.GOOGLE
        assert str(updated.avatar.value) == "https://example.com/pic.jpg"
        user_repo.set_avatar.assert_awaited_once()

    async def it_rejects_google_source_when_no_google_account_is_linked(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(user, AuthProviderName.GOOGLE)

        user_repo.set_avatar.assert_not_called()

    async def it_rejects_google_source_when_linked_but_no_picture(service: UserService):
        user = UserFactory.build(
            linked_providers=[
                LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1", picture_url=None)
            ]
        )

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(user, AuthProviderName.GOOGLE)

    async def it_uses_the_linked_gravatar_picture(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GRAVATAR,
                    external_id="wp-1",
                    picture_url=HttpUrl("https://gravatar.com/avatar/somehash"),
                )
            ]
        )
        user_repo.set_avatar.return_value = True

        updated = await service.set_avatar_source(user, AuthProviderName.GRAVATAR)

        assert updated.avatar is not None
        assert updated.avatar.source == AuthProviderName.GRAVATAR
        assert str(updated.avatar.value) == "https://gravatar.com/avatar/somehash"

    async def it_rejects_gravatar_source_when_no_gravatar_account_is_linked(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(user, AuthProviderName.GRAVATAR)

        user_repo.set_avatar.assert_not_called()

    async def it_rejects_gravatar_source_when_linked_but_no_picture(service: UserService):
        user = UserFactory.build(
            linked_providers=[
                LinkedProviderSchema(provider=AuthProviderName.GRAVATAR, external_id="wp-1", picture_url=None)
            ]
        )

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(user, AuthProviderName.GRAVATAR)

    async def it_raises_when_the_user_vanishes_between_read_and_write(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GOOGLE,
                    external_id="sub-1",
                    picture_url=HttpUrl("https://example.com/pic.jpg"),
                )
            ]
        )
        user_repo.set_avatar.return_value = False

        with pytest.raises(InvalidCredentialsError):
            await service.set_avatar_source(user, AuthProviderName.GOOGLE)


def describe_clear_avatar():
    async def it_clears_the_active_avatar(service: UserService, user_repo: AsyncMock):
        user_repo.clear_avatar.return_value = True

        await service.clear_avatar(SOME_USER_ID)

        user_repo.clear_avatar.assert_awaited_once_with(SOME_USER_ID)

    async def it_raises_when_the_user_vanishes_between_read_and_write(service: UserService, user_repo: AsyncMock):
        user_repo.clear_avatar.return_value = False

        with pytest.raises(InvalidCredentialsError):
            await service.clear_avatar(SOME_USER_ID)


def describe_regenerate_avatar_seed():
    async def it_replaces_the_persisted_seed(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(id=SOME_USER_ID, generated_avatar_seed="stable-seed")
        user_repo.set_generated_avatar_seed.return_value = True

        updated = await service.regenerate_avatar_seed(user)

        assert updated.generated_avatar_seed != "stable-seed"
        user_repo.set_generated_avatar_seed.assert_awaited_once()
        call_args = user_repo.set_generated_avatar_seed.call_args.args
        assert call_args[0] == SOME_USER_ID
        assert call_args[1] == updated.generated_avatar_seed

    async def it_raises_when_the_user_vanishes_between_read_and_write(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()
        user_repo.set_generated_avatar_seed.return_value = False

        with pytest.raises(InvalidCredentialsError):
            await service.regenerate_avatar_seed(user)


def describe_accept_legal_documents():
    async def it_rejects_a_stale_terms_version(service: UserService):
        user = UserFactory.build()
        with pytest.raises(StaleLegalVersionError):
            await service.accept_legal_documents(user, terms_version=0, privacy_version=1)

    async def it_rejects_a_stale_privacy_version(service: UserService):
        user = UserFactory.build()
        with pytest.raises(StaleLegalVersionError):
            await service.accept_legal_documents(user, terms_version=1, privacy_version=0)

    async def it_sets_profile_completed_at_the_first_time(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(profile_completed_at=None)
        user_repo.set_legal_acceptance.return_value = True

        updated = await service.accept_legal_documents(user, terms_version=1, privacy_version=1)

        assert updated.accepted_terms_version == 1
        assert updated.accepted_privacy_version == 1
        assert updated.profile_completed_at is not None
        call_kwargs = user_repo.set_legal_acceptance.call_args.kwargs
        assert call_kwargs["profile_completed_at"] == updated.profile_completed_at

    async def it_preserves_the_original_profile_completed_at_on_reacceptance(
        service: UserService, user_repo: AsyncMock
    ):
        original_completed_at = datetime(2025, 1, 1, tzinfo=UTC)
        user = UserFactory.build(profile_completed_at=original_completed_at)
        user_repo.set_legal_acceptance.return_value = True

        updated = await service.accept_legal_documents(user, terms_version=1, privacy_version=1)

        assert updated.profile_completed_at == original_completed_at

    async def it_raises_when_the_user_vanishes_between_read_and_write(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build()
        user_repo.set_legal_acceptance.return_value = False

        with pytest.raises(InvalidCredentialsError):
            await service.accept_legal_documents(user, terms_version=1, privacy_version=1)


def describe_get_email_preferences():
    async def it_returns_cached_preferences_when_available(
        service: UserService, cache_repo: AsyncMock, user_repo: AsyncMock
    ):
        email = "a@b.com"
        expected_prefs = EmailPreferencesSchema()
        cached_payload = json.dumps(expected_prefs.model_dump(mode="json"))

        cache_repo.find.return_value = {"payload": cached_payload}

        prefs = await service.get_email_preferences(email)

        assert isinstance(prefs, EmailPreferencesSchema)
        user_repo.find_email_preferences_by_email.assert_not_called()

    async def it_falls_back_to_db_when_cache_contains_malformed_json(
        service: UserService, cache_repo: AsyncMock, user_repo: AsyncMock
    ):
        email = "a@b.com"
        cache_repo.find.return_value = {"payload": "invalid-json{"}
        db_prefs = EmailPreferencesSchema()
        user_repo.find_email_preferences_by_email.return_value = db_prefs

        prefs = await service.get_email_preferences(email)

        assert prefs == db_prefs
        user_repo.find_email_preferences_by_email.assert_awaited_once_with(email)
        cache_repo.save.assert_awaited_once()

    async def it_returns_default_preferences_if_not_found_in_db(
        service: UserService, cache_repo: AsyncMock, user_repo: AsyncMock
    ):
        email = "unknown@b.com"
        cache_repo.find.return_value = None
        user_repo.find_email_preferences_by_email.return_value = None

        prefs = await service.get_email_preferences(email)

        assert isinstance(prefs, EmailPreferencesSchema)
        cache_repo.save.assert_not_called()


def describe_is_verified_email():
    async def it_delegates_verification_check_to_user_repo(service: UserService, user_repo: AsyncMock):
        user_repo.is_email_verified_by_id.return_value = True

        result = await service.is_verified_email(SOME_USER_ID)

        assert result is True
        user_repo.is_email_verified_by_id.assert_awaited_once_with(SOME_USER_ID)


def describe_get_by_ids():
    async def it_delegates_fetching_multiple_users_to_user_repo(service: UserService, user_repo: AsyncMock):
        user_ids = [SOME_USER_ID]
        user_repo.get_by_ids.return_value = [UserFactory.build()]

        users = await service.get_by_ids(user_ids)

        assert len(users) == 1
        user_repo.get_by_ids.assert_awaited_once_with(user_ids)


def describe_get_id_by_username():
    async def it_returns_user_id_when_found(service: UserService, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_USER_ID

        user_id = await service.get_id_by_username("alice_1")

        assert user_id == SOME_USER_ID
        user_repo.find_id_by_username.assert_awaited_once_with("alice_1")

    async def it_raises_user_not_found_error_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.get_id_by_username("missing_user")


def describe_find_by_id():
    async def it_delegates_to_user_repo(service: UserService, user_repo: AsyncMock):
        fake_user = UserFactory.build(id=SOME_USER_ID)
        user_repo.find_by_id.return_value = fake_user

        assert await service.find_by_id(SOME_USER_ID) is fake_user
        user_repo.find_by_id.assert_awaited_once_with(SOME_USER_ID)

    async def it_returns_none_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None

        assert await service.find_by_id(SOME_USER_ID) is None


def describe_find_by_identifier():
    async def it_delegates_to_user_repo(service: UserService, user_repo: AsyncMock):
        fake_user = UserFactory.build(id=SOME_USER_ID)
        user_repo.find_by_identifier.return_value = fake_user

        assert await service.find_by_identifier("alice@example.com") is fake_user
        user_repo.find_by_identifier.assert_awaited_once_with("alice@example.com")

    async def it_returns_none_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_by_identifier.return_value = None

        assert await service.find_by_identifier("nobody@example.com") is None


def describe_get_id_by_identifier():
    async def it_returns_user_id_when_found(service: UserService, user_repo: AsyncMock):
        user_repo.find_id_by_identifier.return_value = SOME_USER_ID

        user_id = await service.get_id_by_identifier("alice@example.com")

        assert user_id == SOME_USER_ID
        user_repo.find_id_by_identifier.assert_awaited_once_with("alice@example.com")

    async def it_raises_user_not_found_error_when_missing(service: UserService, user_repo: AsyncMock):
        user_repo.find_id_by_identifier.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.get_id_by_identifier("nobody@example.com")


def describe_mark_email_as_verified():
    async def it_delegates_to_user_repo_with_a_timestamp(service: UserService, user_repo: AsyncMock):
        await service.mark_email_as_verified(user_id=SOME_USER_ID)

        user_repo.mark_email_as_verified.assert_awaited_once()
        call_kwargs = user_repo.mark_email_as_verified.call_args.kwargs
        assert call_kwargs["user_id"] == SOME_USER_ID
        assert isinstance(call_kwargs["verified_at"], datetime)


def describe_process_unsubscribe():
    async def it_applies_a_club_scoped_opt_out_and_invalidates_the_cache(
        service: UserService, user_repo: AsyncMock, cache_repo: AsyncMock
    ):
        user = UserFactory.build(id=SOME_USER_ID, email="alice@example.com")
        user_repo.find_by_id.return_value = user
        token_data = UnsubscribeTokenData(scope=UnsubscribeScope.CLUB, user_id=SOME_USER_ID, club_id=SOME_CLUB_ID)

        result = await service.process_unsubscribe(token_data)

        assert result == UnsubscribeScope.CLUB
        user_repo.opt_out_club_by_id.assert_awaited_once()
        awaited_args = user_repo.opt_out_club_by_id.await_args.args
        assert awaited_args[0] == SOME_USER_ID
        assert awaited_args[1] == SOME_CLUB_ID
        assert isinstance(awaited_args[2], datetime)
        user_repo.opt_out_category_by_id.assert_not_called()
        cache_repo.invalidate.assert_awaited_once()

    async def it_applies_a_category_scoped_opt_out(service: UserService, user_repo: AsyncMock):
        user = UserFactory.build(id=SOME_USER_ID, email="alice@example.com")
        user_repo.find_by_id.return_value = user
        token_data = UnsubscribeTokenData(
            scope=UnsubscribeScope.CATEGORY, user_id=SOME_USER_ID, category=EmailCategory.ENGAGEMENT
        )

        result = await service.process_unsubscribe(token_data)

        assert result == UnsubscribeScope.CATEGORY
        user_repo.opt_out_category_by_id.assert_awaited_once()
        awaited_args = user_repo.opt_out_category_by_id.await_args.args
        assert awaited_args[0] == SOME_USER_ID
        assert awaited_args[1] == EmailCategory.ENGAGEMENT
        user_repo.opt_out_club_by_id.assert_not_called()

    async def it_raises_user_not_found_error_when_the_token_targets_a_missing_user(
        service: UserService, user_repo: AsyncMock
    ):
        user_repo.find_by_id.return_value = None
        token_data = UnsubscribeTokenData(scope=UnsubscribeScope.CLUB, user_id=SOME_USER_ID, club_id=SOME_CLUB_ID)

        with pytest.raises(UserNotFoundError):
            await service.process_unsubscribe(token_data)

        user_repo.opt_out_club_by_id.assert_not_called()
