from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from pydantic import HttpUrl

from canterlot.exceptions import (
    AuthProviderNotLinkedError,
    InvalidCredentialsError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.models.book import ReadBook
from canterlot.models.user import AvatarSchema, LinkedProviderSchema, UserModel
from canterlot.services.user import UserService
from canterlot.types import AuthProviderName

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def _user(**overrides: object) -> UserModel:
    defaults = {"name": "Alice Smith", "username": "alice_1", "email": "a@b.com"}
    return UserModel(**{**defaults, **overrides})


def describe_marking_a_book_as_read():
    async def it_appends_the_book_to_the_users_reading_history(user_repo: AsyncMock):
        service = UserService(user_repo)

        await service.mark_book_read(user_id=SOME_USER_ID, book_id=SOME_BOOK_ID)

        user_repo.push_read_book_by_id.assert_awaited_once()
        call_kwargs = user_repo.push_read_book_by_id.call_args.kwargs
        assert call_kwargs["user_id"] == SOME_USER_ID
        assert isinstance(call_kwargs["read_book"], ReadBook)
        assert call_kwargs["read_book"].id == SOME_BOOK_ID


def describe_update_profile():
    async def it_updates_both_fields(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.exists_by_username.return_value = False
        user_repo.update_profile.return_value = True
        service = UserService(user_repo)

        updated = await service.update_profile(SOME_USER_ID, name="Alice Sparkle", username="new_alice")

        assert updated.name == "Alice Sparkle"
        assert updated.username == "new_alice"
        user_repo.update_profile.assert_awaited_once_with(SOME_USER_ID, name="Alice Sparkle", username="new_alice")

    async def it_updates_only_the_provided_field(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.update_profile.return_value = True
        service = UserService(user_repo)

        updated = await service.update_profile(SOME_USER_ID, name="Alice Sparkle", username=None)

        assert updated.name == "Alice Sparkle"
        assert updated.username == "alice_1"
        user_repo.exists_by_username.assert_not_called()

    async def it_allows_resubmitting_the_users_own_current_username(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.update_profile.return_value = True
        service = UserService(user_repo)

        await service.update_profile(SOME_USER_ID, name=None, username="alice_1")

        user_repo.exists_by_username.assert_not_called()

    async def it_rejects_a_username_already_taken_by_someone_else(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.exists_by_username.return_value = True
        service = UserService(user_repo)

        with pytest.raises(UsernameAlreadyExistsError):
            await service.update_profile(SOME_USER_ID, name=None, username="taken")

        user_repo.update_profile.assert_not_called()

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.update_profile(SOME_USER_ID, name="Alice Sparkle", username=None)

    async def it_raises_when_the_user_vanishes_between_read_and_write(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.update_profile.return_value = False
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.update_profile(SOME_USER_ID, name="Alice Sparkle", username=None)


def describe_get_profile():
    async def it_returns_the_user(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        service = UserService(user_repo)

        user = await service.get_profile(SOME_USER_ID)

        assert user.username == "alice_1"

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.get_profile(SOME_USER_ID)


def describe_find_profile_by_id():
    async def it_returns_the_user_when_found(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        service = UserService(user_repo)

        user = await service.find_profile_by_id(SOME_USER_ID)

        assert user is not None
        assert user.username == "alice_1"

    async def it_returns_none_without_raising_when_missing(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        user = await service.find_profile_by_id(SOME_USER_ID)

        assert user is None


def describe_set_avatar_source():
    async def it_uses_the_linked_google_picture(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GOOGLE,
                    external_id="sub-1",
                    picture_url=HttpUrl("https://example.com/pic.jpg"),
                )
            ]
        )
        user_repo.set_avatar.return_value = True
        service = UserService(user_repo)

        updated = await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GOOGLE)

        assert updated.avatar is not None
        assert updated.avatar.source == AuthProviderName.GOOGLE
        assert str(updated.avatar.value) == "https://example.com/pic.jpg"
        user_repo.set_avatar.assert_awaited_once()

    async def it_rejects_google_source_when_no_google_account_is_linked(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        service = UserService(user_repo)

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GOOGLE)

        user_repo.set_avatar.assert_not_called()

    async def it_rejects_google_source_when_linked_but_no_picture(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            linked_providers=[
                LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1", picture_url=None)
            ]
        )
        service = UserService(user_repo)

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GOOGLE)

    async def it_uses_the_linked_gravatar_picture(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GRAVATAR,
                    external_id="wp-1",
                    picture_url=HttpUrl("https://gravatar.com/avatar/somehash"),
                )
            ]
        )
        user_repo.set_avatar.return_value = True
        service = UserService(user_repo)

        updated = await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GRAVATAR)

        assert updated.avatar is not None
        assert updated.avatar.source == AuthProviderName.GRAVATAR
        assert str(updated.avatar.value) == "https://gravatar.com/avatar/somehash"

    async def it_rejects_gravatar_source_when_no_gravatar_account_is_linked(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        service = UserService(user_repo)

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GRAVATAR)

        user_repo.set_avatar.assert_not_called()

    async def it_rejects_gravatar_source_when_linked_but_no_picture(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            linked_providers=[
                LinkedProviderSchema(provider=AuthProviderName.GRAVATAR, external_id="wp-1", picture_url=None)
            ]
        )
        service = UserService(user_repo)

        with pytest.raises(AuthProviderNotLinkedError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GRAVATAR)

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GOOGLE)

    async def it_raises_when_the_user_vanishes_between_read_and_write(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            linked_providers=[
                LinkedProviderSchema(
                    provider=AuthProviderName.GOOGLE,
                    external_id="sub-1",
                    picture_url=HttpUrl("https://example.com/pic.jpg"),
                )
            ]
        )
        user_repo.set_avatar.return_value = False
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.set_avatar_source(SOME_USER_ID, AuthProviderName.GOOGLE)


def describe_clear_avatar():
    async def it_clears_the_active_avatar(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(
            avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=HttpUrl("https://example.com/pic.jpg"))
        )
        user_repo.clear_avatar.return_value = True
        service = UserService(user_repo)

        updated = await service.clear_avatar(SOME_USER_ID)

        assert updated.avatar is None
        user_repo.clear_avatar.assert_awaited_once_with(SOME_USER_ID)

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.clear_avatar(SOME_USER_ID)

    async def it_raises_when_the_user_vanishes_between_read_and_write(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.clear_avatar.return_value = False
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.clear_avatar(SOME_USER_ID)


def describe_regenerate_avatar_seed():
    async def it_replaces_the_persisted_seed(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(generated_avatar_seed="stable-seed")
        user_repo.set_generated_avatar_seed.return_value = True
        service = UserService(user_repo)

        updated = await service.regenerate_avatar_seed(SOME_USER_ID)

        assert updated.generated_avatar_seed != "stable-seed"
        user_repo.set_generated_avatar_seed.assert_awaited_once()
        call_args = user_repo.set_generated_avatar_seed.call_args.args
        assert call_args[0] == SOME_USER_ID
        assert call_args[1] == updated.generated_avatar_seed

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.regenerate_avatar_seed(SOME_USER_ID)

    async def it_raises_when_the_user_vanishes_between_read_and_write(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.set_generated_avatar_seed.return_value = False
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.regenerate_avatar_seed(SOME_USER_ID)


def describe_accept_legal_documents():
    async def it_rejects_a_stale_terms_version(user_repo: AsyncMock):
        service = UserService(user_repo)

        with pytest.raises(StaleLegalVersionError):
            await service.accept_legal_documents(SOME_USER_ID, terms_version=0, privacy_version=1)

        user_repo.find_by_id.assert_not_called()

    async def it_rejects_a_stale_privacy_version(user_repo: AsyncMock):
        service = UserService(user_repo)

        with pytest.raises(StaleLegalVersionError):
            await service.accept_legal_documents(SOME_USER_ID, terms_version=1, privacy_version=0)

    async def it_sets_profile_completed_at_the_first_time(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user(profile_completed_at=None)
        user_repo.set_legal_acceptance.return_value = True
        service = UserService(user_repo)

        updated = await service.accept_legal_documents(SOME_USER_ID, terms_version=1, privacy_version=1)

        assert updated.accepted_terms_version == 1
        assert updated.accepted_privacy_version == 1
        assert updated.profile_completed_at is not None
        call_kwargs = user_repo.set_legal_acceptance.call_args.kwargs
        assert call_kwargs["profile_completed_at"] == updated.profile_completed_at

    async def it_preserves_the_original_profile_completed_at_on_reacceptance(user_repo: AsyncMock):
        original_completed_at = datetime(2025, 1, 1, tzinfo=UTC)
        user_repo.find_by_id.return_value = _user(profile_completed_at=original_completed_at)
        user_repo.set_legal_acceptance.return_value = True
        service = UserService(user_repo)

        updated = await service.accept_legal_documents(SOME_USER_ID, terms_version=1, privacy_version=1)

        assert updated.profile_completed_at == original_completed_at

    async def it_raises_when_the_user_record_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.accept_legal_documents(SOME_USER_ID, terms_version=1, privacy_version=1)

    async def it_raises_when_the_user_vanishes_between_read_and_write(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = _user()
        user_repo.set_legal_acceptance.return_value = False
        service = UserService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.accept_legal_documents(SOME_USER_ID, terms_version=1, privacy_version=1)
