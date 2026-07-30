from unittest.mock import AsyncMock, call

import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.config import get_settings
from canterlot.constants import (
    CLUB_MODERATION_RATELIMIT_TEMPLATE,
    CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE,
    INVITE_CREATE_DIRECT_RATELIMIT_TEMPLATE,
    LOGIN_ACCOUNT_RATELIMIT_TEMPLATE,
    LOGIN_IP_RATELIMIT_TEMPLATE,
    OAUTH_SIGNIN_RATELIMIT_TEMPLATE,
    PASSWORD_CHANGE_RATELIMIT_TEMPLATE,
    PASSWORD_RESET_REQUEST_RATELIMIT_TEMPLATE,
    PROVIDER_MUTATION_RATELIMIT_TEMPLATE,
    REFRESH_RATELIMIT_TEMPLATE,
    REGISTER_RATELIMIT_TEMPLATE,
)
from canterlot.exceptions import RateLimitExceededError
from canterlot.repositories.interfaces import RateLimiter
from canterlot.routers.dependencies.rate_limiter import (
    rate_limit_club_moderation,
    rate_limit_club_owner_action,
    rate_limit_create_invite_attempt,
    rate_limit_login_attempt,
    rate_limit_password_change_attempt,
    rate_limit_password_reset_request_attempt,
    rate_limit_provider_mutation_attempt,
    rate_limit_refresh_attempt,
    rate_limit_register_attempt,
)
from canterlot.types import AuthProviderName, InviteType, SessionType
from tools.factories import CreateInviteRequestFactory, CreateSessionRequestFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_PASSWORD = SecretStr("secret")


def describe_rate_limit_club_owner_action():
    async def it_keys_the_counter_by_scope_club_and_caller():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0
        dependency = rate_limit_club_owner_action("club-ownership-action")

        await dependency(club_id=SOME_CLUB_ID, current_user_id=SOME_USER_ID, rate_limiter=rate_limiter)

        settings = get_settings().ratelimit
        expected_key = CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE.format(
            scope="club-ownership-action",
            club_id=SOME_CLUB_ID,
            user_id=SOME_USER_ID,
        )
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.club_ownership_action,
            settings.club_ownership_action_window_seconds,
        )

    async def it_raises_once_the_configured_limit_is_exceeded():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 10
        dependency = rate_limit_club_owner_action("club-ownership-action")

        with pytest.raises(RateLimitExceededError) as exc_info:
            await dependency(club_id=SOME_CLUB_ID, current_user_id=SOME_USER_ID, rate_limiter=rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "10"}


def describe_rate_limit_register_attempt():
    async def it_keys_the_counter_by_client_ip(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        request = make_request("203.0.113.5")
        await rate_limit_register_attempt(request, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = REGISTER_RATELIMIT_TEMPLATE.format(ip="203.0.113.5")
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.auth_register,
            settings.auth_register_window_seconds,
        )

    async def it_falls_back_to_unknown_ip_when_client_is_absent(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        request = make_request(None)
        await rate_limit_register_attempt(request, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = REGISTER_RATELIMIT_TEMPLATE.format(ip="unknown")
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.auth_register,
            settings.auth_register_window_seconds,
        )

    async def it_raises_once_the_configured_limit_is_exceeded(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 10

        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limit_register_attempt(make_request(), rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "10"}


def describe_rate_limit_refresh_attempt():
    async def it_keys_the_counter_by_client_ip(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        request = make_request("203.0.113.5")
        await rate_limit_refresh_attempt(request, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = REFRESH_RATELIMIT_TEMPLATE.format(ip="203.0.113.5")
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.auth_refresh,
            settings.auth_refresh_window_seconds,
        )

    async def it_raises_once_the_configured_limit_is_exceeded(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 10

        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limit_refresh_attempt(make_request(), rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "10"}


def describe_rate_limit_login_attempt():
    async def it_applies_a_single_ip_keyed_limit_for_oauth_sessions(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0
        payload = CreateSessionRequestFactory.build(
            type=SessionType.OAUTH, provider=AuthProviderName.GOOGLE, credential="token"
        )

        request = make_request("203.0.113.5")
        await rate_limit_login_attempt(request, payload, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = OAUTH_SIGNIN_RATELIMIT_TEMPLATE.format(ip="203.0.113.5")
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.auth_oauth_signin,
            settings.auth_oauth_signin_window_seconds,
        )

    async def it_applies_ip_and_account_keyed_limits_for_password_sessions(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0
        payload = CreateSessionRequestFactory.build(
            type=SessionType.PASSWORD, username="alice_1", password=SOME_PASSWORD
        )

        request = make_request("203.0.113.5")
        await rate_limit_login_attempt(request, payload, rate_limiter)

        settings = get_settings().ratelimit
        expected_ip_key = LOGIN_IP_RATELIMIT_TEMPLATE.format(ip="203.0.113.5")
        expected_account_key = LOGIN_ACCOUNT_RATELIMIT_TEMPLATE.format(username="alice_1")

        assert rate_limiter.evaluate.await_args_list == [
            call(expected_ip_key, settings.auth_login_ip, settings.auth_login_window_seconds),
            call(expected_account_key, settings.auth_login_account, settings.auth_login_window_seconds),
        ]

    async def it_raises_when_the_ip_limit_is_exceeded_for_a_password_session(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 10
        payload = CreateSessionRequestFactory.build(
            type=SessionType.PASSWORD, username="alice_1", password=SOME_PASSWORD
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limit_login_attempt(make_request(), payload, rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "10"}

    async def it_raises_when_the_account_limit_is_exceeded_for_a_password_session(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.side_effect = [0, 10]
        payload = CreateSessionRequestFactory.build(
            type=SessionType.PASSWORD, username="alice_1", password=SOME_PASSWORD
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limit_login_attempt(make_request(), payload, rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "10"}


def describe_rate_limit_create_invite_attempt():
    async def it_skips_rate_limiting_for_public_invites():
        rate_limiter = AsyncMock(spec=RateLimiter)
        payload = CreateInviteRequestFactory.build(type=InviteType.PUBLIC)

        await rate_limit_create_invite_attempt(payload, SOME_USER_ID, rate_limiter)

        rate_limiter.evaluate.assert_not_called()

    async def it_applies_limit_for_direct_invites():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0
        payload = CreateInviteRequestFactory.build(type=InviteType.DIRECT, email="target@example.com")

        await rate_limit_create_invite_attempt(payload, SOME_USER_ID, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = INVITE_CREATE_DIRECT_RATELIMIT_TEMPLATE.format(user_id=SOME_USER_ID)
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.invite_create_direct,
            settings.invite_create_direct_window_seconds,
        )


def describe_rate_limit_password_change_attempt():
    async def it_keys_the_counter_by_current_user_id():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        await rate_limit_password_change_attempt(SOME_USER_ID, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = PASSWORD_CHANGE_RATELIMIT_TEMPLATE.format(user_id=SOME_USER_ID)
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.password_change,
            settings.password_change_window_seconds,
        )


def describe_rate_limit_password_reset_request_attempt():
    async def it_keys_the_counter_by_client_ip(make_request):
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        request = make_request("203.0.113.5")
        await rate_limit_password_reset_request_attempt(request, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = PASSWORD_RESET_REQUEST_RATELIMIT_TEMPLATE.format(ip="203.0.113.5")
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.password_reset_request,
            settings.password_reset_request_window_seconds,
        )


def describe_rate_limit_provider_mutation_attempt():
    async def it_keys_the_counter_by_current_user_id():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0

        await rate_limit_provider_mutation_attempt(SOME_USER_ID, rate_limiter)

        settings = get_settings().ratelimit
        expected_key = PROVIDER_MUTATION_RATELIMIT_TEMPLATE.format(user_id=SOME_USER_ID)
        rate_limiter.evaluate.assert_awaited_once_with(
            expected_key,
            settings.provider_mutation,
            settings.provider_mutation_window_seconds,
        )


def describe_rate_limit_club_moderation():
    async def it_keys_the_counter_by_club_user_and_action():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 0
        dependency = rate_limit_club_moderation("remove_member")

        await dependency(club_id=SOME_CLUB_ID, current_user_id=SOME_USER_ID, rate_limiter=rate_limiter)

        settings = get_settings().ratelimit
        expected_key = CLUB_MODERATION_RATELIMIT_TEMPLATE.format(
            club_id=SOME_CLUB_ID,
            user_id=SOME_USER_ID,
            action="remove_member",
        )
        rate_limiter.evaluate.assert_awaited_once_with(
            key=expected_key,
            limit=settings.club_moderation_action,
            window_seconds=settings.club_moderation_action_window_seconds,
        )

    async def it_raises_when_limit_is_exceeded():
        rate_limiter = AsyncMock(spec=RateLimiter)
        rate_limiter.evaluate.return_value = 15
        dependency = rate_limit_club_moderation("remove_member")

        with pytest.raises(RateLimitExceededError) as exc_info:
            await dependency(club_id=SOME_CLUB_ID, current_user_id=SOME_USER_ID, rate_limiter=rate_limiter)

        assert exc_info.value.headers == {"Retry-After": "15"}
