from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.auth import UserRegisterRequest
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    LastAuthenticationMethodError,
    OAuthAccountCreationConflictError,
    UsernameAlreadyExistsError,
)
from canterlot.models.enums import AuthOutcome, AuthProviderName
from canterlot.models.user import LinkedProviderSchema
from canterlot.providers.auth import OAuthIdentity, OAuthProvider
from canterlot.services.auth import AuthService
from canterlot.utils.security import hash_password

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_OTHER_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def _register_request(**overrides) -> UserRegisterRequest:
    defaults = {"name": "Alice Smith", "username": "alice_1", "email": "alice@example.com", "password": "secret1"}
    return UserRegisterRequest(**{**defaults, **overrides})


def _google_provider() -> AsyncMock:
    return AsyncMock(spec=OAuthProvider)


def describe_register_user():
    async def it_rejects_registration_when_the_username_is_taken(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = True
        service = AuthService(user_repo, {})

        with pytest.raises(UsernameAlreadyExistsError):
            await service.register_user(_register_request())

        user_repo.exists_by_email.assert_not_called()

    async def it_rejects_registration_when_the_email_is_taken(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = False
        user_repo.exists_by_email.return_value = True
        service = AuthService(user_repo, {})

        with pytest.raises(EmailAlreadyExistsError):
            await service.register_user(_register_request())

    async def it_persists_a_new_user_and_returns_issued_tokens(user_repo: AsyncMock):
        user_repo.exists_by_username.return_value = False
        user_repo.exists_by_email.return_value = False
        user_repo.save.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo, {})

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
        service = AuthService(user_repo, {})

        await service.register_user(_register_request(), invited_by="referrer_1")

        user_repo.increment_referral_count_by_username.assert_awaited_once_with("referrer_1")


def describe_login_user():
    async def it_issues_tokens_for_valid_credentials(user_repo: AsyncMock):
        hashed = hash_password("secret1")
        user_repo.find_by_username.return_value = SimpleNamespace(id=SOME_USER_ID, hashed_password=hashed)
        service = AuthService(user_repo, {})

        result = await service.login_user("alice_1", "secret1")

        assert result.access_token
        assert result.refresh_token
        user_repo.push_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, result.refresh_token)

    async def it_rejects_a_login_for_an_unknown_username(user_repo: AsyncMock):
        user_repo.find_by_username.return_value = None
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.login_user("ghost", "secret1")

    async def it_rejects_a_login_with_an_incorrect_password(user_repo: AsyncMock):
        hashed = hash_password("secret1")
        user_repo.find_by_username.return_value = SimpleNamespace(id=SOME_USER_ID, hashed_password=hashed)
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.login_user("alice_1", "wrong-password")

    async def it_rejects_a_password_login_for_an_oauth_only_account(user_repo: AsyncMock):
        user_repo.find_by_username.return_value = SimpleNamespace(id=SOME_USER_ID, hashed_password=None)
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.login_user("alice_1", "anything")


def describe_rotate_refresh_token():
    async def it_pulls_the_old_token_and_pushes_a_freshly_issued_pair(user_repo: AsyncMock):
        service = AuthService(user_repo, {})

        result = await service.rotate_refresh_token(SOME_USER_ID, "old-token")

        user_repo.pull_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, "old-token")
        user_repo.push_refresh_token_by_id.assert_awaited_once_with(SOME_USER_ID, result.refresh_token)
        assert result.access_token


def describe_sign_in_with_provider():
    async def it_raises_when_the_provider_is_not_configured(user_repo: AsyncMock):
        service = AuthService(user_repo, {})

        with pytest.raises(GatewayConfigurationError):
            await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

    async def it_logs_in_when_the_identity_matches_an_existing_linked_account(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name="Alice")
        user_repo.find_id_by_linked_provider.return_value = SOME_USER_ID
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        result = await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

        assert result.outcome == AuthOutcome.LOGGED_IN
        assert result.access_token
        assert result.refresh_token
        user_repo.save_new_oauth_account.assert_not_called()

    async def it_requires_linking_when_the_email_already_belongs_to_a_different_account(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name="Alice")
        user_repo.find_id_by_linked_provider.return_value = None
        user_repo.find_by_email.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        result = await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

        assert result.outcome == AuthOutcome.LINK_REQUIRED
        assert result.access_token is None
        assert result.refresh_token is None
        user_repo.save_new_oauth_account.assert_not_called()

    async def it_creates_a_new_account_when_no_match_exists(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name="Alice")
        user_repo.find_id_by_linked_provider.return_value = None
        user_repo.find_by_email.return_value = None
        user_repo.exists_by_username.return_value = False
        user_repo.save_new_oauth_account.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        result = await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

        assert result.outcome == AuthOutcome.CREATED
        assert result.access_token
        saved_user = user_repo.save_new_oauth_account.call_args.args[0]
        assert saved_user.username == "alice"
        assert saved_user.hashed_password is None
        assert len(saved_user.linked_providers) == 1
        assert saved_user.linked_providers[0].provider == AuthProviderName.GOOGLE
        assert saved_user.linked_providers[0].external_id == "sub-1"

    async def it_falls_back_to_the_email_local_part_for_the_username_when_no_name_is_given(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name=None)
        user_repo.find_id_by_linked_provider.return_value = None
        user_repo.find_by_email.return_value = None
        user_repo.exists_by_username.return_value = False
        user_repo.save_new_oauth_account.return_value = SimpleNamespace(id=SOME_USER_ID)
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

        saved_user = user_repo.save_new_oauth_account.call_args.args[0]
        assert saved_user.name == "alice"

    async def it_logs_into_the_winning_account_when_a_concurrent_sign_up_wins_the_race(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name="Alice")
        user_repo.find_id_by_linked_provider.side_effect = [None, SOME_OTHER_USER_ID]
        user_repo.find_by_email.return_value = None
        user_repo.exists_by_username.return_value = False
        user_repo.save_new_oauth_account.return_value = None
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        result = await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")

        assert result.outcome == AuthOutcome.LOGGED_IN
        assert result.access_token

    async def it_raises_when_a_create_conflict_leaves_no_matching_account_behind(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com", name="Alice")
        user_repo.find_id_by_linked_provider.side_effect = [None, None]
        user_repo.find_by_email.return_value = None
        user_repo.exists_by_username.return_value = False
        user_repo.save_new_oauth_account.return_value = None
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        with pytest.raises(OAuthAccountCreationConflictError):
            await service.sign_in_with_provider(AuthProviderName.GOOGLE, "some-credential")


def describe_link_provider():
    async def it_raises_when_the_provider_is_not_configured(user_repo: AsyncMock):
        service = AuthService(user_repo, {})

        with pytest.raises(GatewayConfigurationError):
            await service.link_provider(SOME_USER_ID, AuthProviderName.GOOGLE, "some-credential")

    async def it_links_the_provider_when_unclaimed(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com")
        user_repo.find_id_by_linked_provider.return_value = None
        user_repo.add_linked_provider.return_value = True
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        await service.link_provider(SOME_USER_ID, AuthProviderName.GOOGLE, "some-credential")

        user_repo.add_linked_provider.assert_awaited_once()
        called_user_id, called_entry = user_repo.add_linked_provider.call_args.args
        assert called_user_id == SOME_USER_ID
        assert called_entry.provider == AuthProviderName.GOOGLE
        assert called_entry.external_id == "sub-1"

    async def it_rejects_linking_when_a_concurrent_request_wins_the_race(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com")
        user_repo.find_id_by_linked_provider.return_value = None
        user_repo.add_linked_provider.return_value = False
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        with pytest.raises(AuthProviderAlreadyLinkedError):
            await service.link_provider(SOME_USER_ID, AuthProviderName.GOOGLE, "some-credential")

    async def it_is_idempotent_when_already_linked_to_the_same_account(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com")
        user_repo.find_id_by_linked_provider.return_value = SOME_USER_ID
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        await service.link_provider(SOME_USER_ID, AuthProviderName.GOOGLE, "some-credential")

        user_repo.add_linked_provider.assert_not_called()

    async def it_rejects_linking_a_credential_already_owned_by_a_different_account(user_repo: AsyncMock):
        google = _google_provider()
        google.verify.return_value = OAuthIdentity(external_id="sub-1", email="alice@example.com")
        user_repo.find_id_by_linked_provider.return_value = SOME_OTHER_USER_ID
        service = AuthService(user_repo, {AuthProviderName.GOOGLE: google})

        with pytest.raises(AuthProviderAlreadyLinkedError):
            await service.link_provider(SOME_USER_ID, AuthProviderName.GOOGLE, "some-credential")

        user_repo.add_linked_provider.assert_not_called()


def describe_disconnect_provider():
    async def it_raises_when_the_authenticated_user_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.disconnect_provider(SOME_USER_ID, AuthProviderName.GOOGLE)

    async def it_raises_when_the_provider_is_not_linked(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password="hash", linked_providers=[])
        service = AuthService(user_repo, {})

        with pytest.raises(AuthProviderNotLinkedError):
            await service.disconnect_provider(SOME_USER_ID, AuthProviderName.GOOGLE)

    async def it_disconnects_when_a_password_remains_as_a_fallback(user_repo: AsyncMock):
        linked = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password="hash", linked_providers=[linked])
        service = AuthService(user_repo, {})

        await service.disconnect_provider(SOME_USER_ID, AuthProviderName.GOOGLE)

        user_repo.remove_linked_provider.assert_awaited_once_with(SOME_USER_ID, AuthProviderName.GOOGLE)

    async def it_rejects_disconnecting_the_only_remaining_authentication_method(user_repo: AsyncMock):
        linked = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=None, linked_providers=[linked])
        service = AuthService(user_repo, {})

        with pytest.raises(LastAuthenticationMethodError):
            await service.disconnect_provider(SOME_USER_ID, AuthProviderName.GOOGLE)

        user_repo.remove_linked_provider.assert_not_called()


def describe_list_connected_providers():
    async def it_raises_when_the_authenticated_user_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.list_connected_providers(SOME_USER_ID)

    async def it_reports_password_and_linked_providers(user_repo: AsyncMock):
        linked = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password="hash", linked_providers=[linked])
        service = AuthService(user_repo, {})

        result = await service.list_connected_providers(SOME_USER_ID)

        assert result.has_password is True
        assert result.linked_providers[0].provider == AuthProviderName.GOOGLE


def describe_change_password():
    async def it_issues_a_fresh_token_pair_and_revokes_other_sessions(user_repo: AsyncMock):
        hashed = hash_password("current-secret")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=hashed)
        service = AuthService(user_repo, {})

        result = await service.change_password(SOME_USER_ID, "current-secret", "new-secret-1")

        assert result.access_token
        assert result.refresh_token
        user_repo.change_password.assert_awaited_once()
        call_args = user_repo.change_password.call_args.args
        assert call_args[0] == SOME_USER_ID
        assert call_args[1] != "current-secret"
        assert call_args[2] == result.refresh_token

    async def it_rejects_an_incorrect_current_password(user_repo: AsyncMock):
        hashed = hash_password("current-secret")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=hashed)
        service = AuthService(user_repo, {})

        with pytest.raises(IncorrectPasswordError):
            await service.change_password(SOME_USER_ID, "wrong-secret", "new-secret-1")

        user_repo.change_password.assert_not_called()

    async def it_rejects_a_missing_current_password_when_one_already_exists(user_repo: AsyncMock):
        hashed = hash_password("current-secret")
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=hashed)
        service = AuthService(user_repo, {})

        with pytest.raises(IncorrectPasswordError):
            await service.change_password(SOME_USER_ID, None, "new-secret-1")

        user_repo.change_password.assert_not_called()

    async def it_sets_an_initial_password_for_an_oauth_only_account(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=None)
        service = AuthService(user_repo, {})

        result = await service.change_password(SOME_USER_ID, None, "new-secret-1")

        assert result.access_token
        assert result.refresh_token
        user_repo.change_password.assert_awaited_once()
        call_args = user_repo.change_password.call_args.args
        assert call_args[0] == SOME_USER_ID
        assert call_args[2] == result.refresh_token

    async def it_ignores_a_submitted_current_password_for_an_oauth_only_account(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = SimpleNamespace(hashed_password=None)
        service = AuthService(user_repo, {})

        result = await service.change_password(SOME_USER_ID, "anything", "new-secret-1")

        assert result.access_token
        user_repo.change_password.assert_awaited_once()

    async def it_raises_when_the_authenticated_user_no_longer_exists(user_repo: AsyncMock):
        user_repo.find_by_id.return_value = None
        service = AuthService(user_repo, {})

        with pytest.raises(InvalidCredentialsError):
            await service.change_password(SOME_USER_ID, "current-secret", "new-secret-1")

        user_repo.change_password.assert_not_called()
