# canterlot/dependencies/rate_limiter.py
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import Depends, Request

from canterlot.config import get_settings
from canterlot.constants import (
    CLUB_MODERATION_RATELIMIT_TEMPLATE,
    CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE,
    EMAIL_VERIFICATION_CONFIRM_RATELIMIT_TEMPLATE,
    EMAIL_VERIFICATION_REQUEST_RATELIMIT_TEMPLATE,
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
from canterlot.dto.auth import CreateSessionRequest
from canterlot.dto.invite import CreateInviteRequest
from canterlot.exceptions import RateLimitExceededError
from canterlot.repositories.interfaces import RateLimiter
from canterlot.types import InviteType, SessionType

from .providers import get_club_id_from_slug, get_current_user_id, get_rate_limiter


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(rate_limiter: RateLimiter, key: str, limit: int, window_seconds: int) -> None:
    ttl = await rate_limiter.evaluate(key, limit, window_seconds)
    if ttl:
        raise RateLimitExceededError(ttl)


def rate_limit_club_owner_action(scope: str):
    async def dependency(
        club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
        current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        settings = get_settings().ratelimit
        key = CLUB_OWNER_ACTION_RATELIMIT_TEMPLATE.format(scope=scope, club_id=club_id, user_id=current_user_id)
        await _enforce_rate_limit(
            rate_limiter,
            key=key,
            limit=settings.club_ownership_action,
            window_seconds=settings.club_ownership_action_window_seconds,
        )

    return dependency


async def rate_limit_register_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    await _enforce_rate_limit(
        rate_limiter,
        key=REGISTER_RATELIMIT_TEMPLATE.format(ip=_client_ip(request)),
        limit=settings.auth_register,
        window_seconds=settings.auth_register_window_seconds,
    )


async def rate_limit_refresh_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    await _enforce_rate_limit(
        rate_limiter,
        key=REFRESH_RATELIMIT_TEMPLATE.format(ip=_client_ip(request)),
        limit=settings.auth_refresh,
        window_seconds=settings.auth_refresh_window_seconds,
    )


async def rate_limit_login_attempt(
    request: Request,
    payload: CreateSessionRequest,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    ip = _client_ip(request)

    if payload.type is SessionType.OAUTH:
        await _enforce_rate_limit(
            rate_limiter,
            key=OAUTH_SIGNIN_RATELIMIT_TEMPLATE.format(ip=ip),
            limit=settings.auth_oauth_signin,
            window_seconds=settings.auth_oauth_signin_window_seconds,
        )
        return

    await _enforce_rate_limit(
        rate_limiter,
        key=LOGIN_IP_RATELIMIT_TEMPLATE.format(ip=ip),
        limit=settings.auth_login_ip,
        window_seconds=settings.auth_login_window_seconds,
    )
    await _enforce_rate_limit(
        rate_limiter,
        key=LOGIN_ACCOUNT_RATELIMIT_TEMPLATE.format(username=payload.username),
        limit=settings.auth_login_account,
        window_seconds=settings.auth_login_window_seconds,
    )


async def rate_limit_create_invite_attempt(
    payload: CreateInviteRequest,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    # Public link rotation does not trigger emails, skip rate limiting
    if payload.type is InviteType.PUBLIC:
        return

    settings = get_settings().ratelimit
    key = INVITE_CREATE_DIRECT_RATELIMIT_TEMPLATE.format(user_id=current_user_id)

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.invite_create_direct,
        window_seconds=settings.invite_create_direct_window_seconds,
    )


async def rate_limit_password_change_attempt(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = PASSWORD_CHANGE_RATELIMIT_TEMPLATE.format(user_id=current_user_id)

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.password_change,
        window_seconds=settings.password_change_window_seconds,
    )


async def rate_limit_password_reset_request_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = PASSWORD_RESET_REQUEST_RATELIMIT_TEMPLATE.format(ip=_client_ip(request))

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.password_reset_request,
        window_seconds=settings.password_reset_request_window_seconds,
    )


async def rate_limit_provider_mutation_attempt(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = PROVIDER_MUTATION_RATELIMIT_TEMPLATE.format(user_id=current_user_id)

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.provider_mutation,
        window_seconds=settings.provider_mutation_window_seconds,
    )


def rate_limit_club_moderation(action_name: str):
    """Parametrized dependency for rate limiting club moderation actions."""

    async def _dependency(
        club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
        current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        settings = get_settings().ratelimit
        key = CLUB_MODERATION_RATELIMIT_TEMPLATE.format(
            club_id=club_id,
            user_id=current_user_id,
            action=action_name,
        )

        ttl = await rate_limiter.evaluate(
            key=key,
            limit=settings.club_moderation_action,
            window_seconds=settings.club_moderation_action_window_seconds,
        )
        if ttl:
            raise RateLimitExceededError(ttl)

    return _dependency


async def rate_limit_password_reset_validation_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = PASSWORD_RESET_REQUEST_RATELIMIT_TEMPLATE.format(ip=_client_ip(request))

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.password_reset_validate,
        window_seconds=settings.password_reset_validate_window_seconds,
    )


async def rate_limit_email_verification_request_attempt(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = EMAIL_VERIFICATION_REQUEST_RATELIMIT_TEMPLATE.format(user_id=current_user_id)

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.email_verification_request,
        window_seconds=settings.email_verification_request_window_seconds,
    )


async def rate_limit_email_verification_confirm_attempt(
    request: Request,
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    settings = get_settings().ratelimit
    key = EMAIL_VERIFICATION_CONFIRM_RATELIMIT_TEMPLATE.format(ip=_client_ip(request))

    await _enforce_rate_limit(
        rate_limiter,
        key=key,
        limit=settings.email_verification_confirm,
        window_seconds=settings.email_verification_confirm_window_seconds,
    )
