from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.auth import UserRegisterRequest
from canterlot.exceptions import EmailAlreadyExistsError, InvalidCredentialsError, UsernameAlreadyExistsError
from canterlot.services.auth import AuthService
from canterlot.utils.security import hash_password

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def _register_request(**overrides) -> UserRegisterRequest:
    defaults = {"name": "Alice Smith", "username": "alice_1", "email": "alice@example.com", "password": "secret1"}
    return UserRegisterRequest(**{**defaults, **overrides})


def describe_register_user():
    async def it_rejects_registration_when_the_username_is_taken(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = True
        service = AuthService(user_repo)

        with pytest.raises(UsernameAlreadyExistsError):
            await service.register_user(_register_request())

        user_repo.exists_by_email.assert_not_called()

    async def it_rejects_registration_when_the_email_is_taken(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = False
        user_repo.exists_by_email.return_value = True
        service = AuthService(user_repo)

        with pytest.raises(EmailAlreadyExistsError):
            await service.register_user(_register_request())

    async def it_persists_a_new_user_and_returns_issued_tokens(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = False
        user_repo.exists_by_email.return_value = False
        user_repo.save.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo)

        result = await service.register_user(_register_request())

        assert result.user_id == SOME_USER_ID
        assert result.access_token
        assert result.refresh_token
        user_repo.push_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, result.refresh_token)
        user_repo.increment_referral_count_by_username.assert_not_called()

    async def it_credits_the_referring_user_when_invited_by_is_given(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = False
        user_repo.exists_by_email.return_value = False
        user_repo.save.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo)

        await service.register_user(_register_request(), invited_by="referrer_1")

        user_repo.increment_referral_count_by_username.assert_awaited_once_with("referrer_1")


def describe_login_user():
    async def it_issues_tokens_for_valid_credentials(user_repo: AsyncMock):
        hashed = hash_password("secret1")
        user_repo.find_by_username.return_value = SimpleNamespace(id=SOME_USER_ID, hashed_password=hashed)
        service = AuthService(user_repo)

        result = await service.login_user("alice_1", "secret1")

        assert result.access_token
        assert result.refresh_token
        user_repo.push_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, result.refresh_token)

    async def it_rejects_a_login_for_an_unknown_username(user_repo: AsyncMock):
        user_repo.find_by_username.return_value = None
        service = AuthService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.login_user("ghost", "secret1")

    async def it_rejects_a_login_with_an_incorrect_password(user_repo: AsyncMock):
        hashed = hash_password("secret1")
        user_repo.find_by_username.return_value = SimpleNamespace(id=SOME_USER_ID, hashed_password=hashed)
        service = AuthService(user_repo)

        with pytest.raises(InvalidCredentialsError):
            await service.login_user("alice_1", "wrong-password")


def describe_rotate_refresh_token():
    async def it_pulls_the_old_token_and_pushes_a_freshly_issued_pair(user_repo: AsyncMock):
        service = AuthService(user_repo)

        result = await service.rotate_refresh_token(SOME_USER_ID, "old-token")

        user_repo.pull_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, "old-token")
        user_repo.push_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, result.refresh_token)
        assert result.access_token
