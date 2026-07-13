from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import InvalidCredentialsError, UsernameAlreadyExistsError
from canterlot.models.book import ReadBook
from canterlot.models.user import UserModel
from canterlot.services.user import UserService

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
