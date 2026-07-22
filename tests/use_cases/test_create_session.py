from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import AuthProviderContext
from canterlot.exceptions import ClubNotFoundError, InvalidInviteTokenError, InviteLinkDeactivatedError
from canterlot.factories import (
    CreateSessionRequestFactory,
    InvitePreviewResponseFactory,
    TokenResponseFactory,
    UserFactory,
)
from canterlot.services.auth import OAuthSignInResult
from canterlot.types import AuthOutcome, AuthProviderName, InviteType, JoinPolicy, SessionType
from canterlot.use_cases.create_session import CreateSessionResult, CreateSessionUseCase


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    invite_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> CreateSessionUseCase:
    return CreateSessionUseCase(
        auth_service=auth_service,
        invite_service=invite_service,
        email_dispatch=email_dispatch_service,
    )


def describe_create_session_use_case():
    def describe_password_session():
        async def it_authenticates_with_password_and_returns_session_tokens(
            use_case: CreateSessionUseCase,
            auth_service: AsyncMock,
            invite_service: AsyncMock,
            email_dispatch_service: AsyncMock,
        ):
            payload = CreateSessionRequestFactory.build(
                type=SessionType.PASSWORD, username="twilight", password=SecretStr("securePassword123!")
            )

            auth_service.login_user.return_value = TokenResponseFactory.build(
                access_token="acc-123",
                refresh_token="ref-456",
            )

            result = await use_case.execute(payload)

            assert isinstance(result, CreateSessionResult)
            assert result.access_token == "acc-123"
            assert result.refresh_token == "ref-456"
            assert result.is_new_user is False
            assert result.location_header is None

            auth_service.login_user.assert_awaited_once_with(
                username="twilight",
                plain_password=SecretStr("securePassword123!"),
            )
            invite_service.get_preview_metadata.assert_not_called()
            email_dispatch_service.dispatch.assert_not_called()

    def describe_oauth_session():
        async def it_logs_in_existing_oauth_user_without_referral_or_welcome_email(
            use_case: CreateSessionUseCase,
            auth_service: AsyncMock,
            invite_service: AsyncMock,
            email_dispatch_service: AsyncMock,
        ):
            payload = CreateSessionRequestFactory.build(
                type=SessionType.OAUTH,
                provider=AuthProviderName.GOOGLE,
                credential="google-id-token-abc",
            )

            user = UserFactory.build()
            auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
                outcome=AuthOutcome.LOGGED_IN,
                access_token="acc-oauth-1",
                refresh_token="ref-oauth-1",
                user=user,
            )

            result = await use_case.execute(payload)

            assert result.access_token == "acc-oauth-1"
            assert result.refresh_token == "ref-oauth-1"
            assert result.is_new_user is False
            assert result.location_header is None

            auth_service.sign_in_with_provider.assert_awaited_once_with(
                AuthProviderName.GOOGLE,
                "google-id-token-abc",
            )
            invite_service.get_preview_metadata.assert_not_called()
            email_dispatch_service.dispatch.assert_not_called()

        async def it_handles_new_user_oauth_creation_with_referral_and_welcome_email(
            use_case: CreateSessionUseCase,
            auth_service: AsyncMock,
            invite_service: AsyncMock,
            email_dispatch_service: AsyncMock,
        ):
            payload = CreateSessionRequestFactory.build(
                type=SessionType.OAUTH,
                provider=AuthProviderName.GOOGLE,
                credential="google-id-token-xyz",
                invite_id="invite-token-789",
                invited_by="celestia",
            )

            user = UserFactory.build()
            auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
                outcome=AuthOutcome.CREATED,
                access_token="acc-oauth-new",
                refresh_token="ref-oauth-new",
                user=user,
            )

            invite_service.get_preview_metadata.return_value = InvitePreviewResponseFactory.build(
                club_slug="canterlot-club",
                club_name="Canterlot Club",
                join_policy=JoinPolicy.PUBLIC,
                invite_type=InviteType.PUBLIC,
                invited_by_username="celestia",
            )

            result = await use_case.execute(payload)

            assert result.is_new_user is True
            assert result.location_header == "/v1/users/me"

            invite_service.get_preview_metadata.assert_awaited_once_with(
                "invite-token-789",
                invited_by="celestia",
            )
            auth_service.attribute_referral.assert_awaited_once_with("celestia")

            email_dispatch_service.dispatch.assert_awaited_once()
            call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
            task_arg = call_kwargs["task"]
            assert isinstance(task_arg, EmailTaskPayload)
            assert task_arg.to == user.email
            assert isinstance(task_arg.context, AuthProviderContext)
            assert call_kwargs["prefs"] == user.email_preferences

        @pytest.mark.parametrize(
            "exception_cls",
            [
                InvalidInviteTokenError,
                InviteLinkDeactivatedError,
                ClubNotFoundError,
            ],
        )
        async def it_gracefully_catches_invite_resolution_errors_during_referral(
            exception_cls: type[Exception],
            use_case: CreateSessionUseCase,
            auth_service: AsyncMock,
            invite_service: AsyncMock,
            email_dispatch_service: AsyncMock,
        ):
            payload = CreateSessionRequestFactory.build(
                type=SessionType.OAUTH,
                provider=AuthProviderName.GOOGLE,
                credential="google-id-token-xyz",
                invite_id="invalid-invite",
            )

            user = UserFactory.build()
            auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
                outcome=AuthOutcome.CREATED,
                access_token="acc-oauth-new",
                refresh_token="ref-oauth-new",
                user=user,
            )

            invite_service.get_preview_metadata.side_effect = exception_cls()

            result = await use_case.execute(payload)

            assert result.is_new_user is True
            invite_service.get_preview_metadata.assert_awaited_once_with(
                "invalid-invite",
                invited_by=None,
            )
            auth_service.attribute_referral.assert_not_called()
            # Welcome email is still dispatched even if referral attribution fails
            email_dispatch_service.dispatch.assert_awaited_once()

        async def it_skips_referral_attribution_if_invite_preview_has_no_inviter_username(
            use_case: CreateSessionUseCase,
            auth_service: AsyncMock,
            invite_service: AsyncMock,
            email_dispatch_service: AsyncMock,
        ):
            payload = CreateSessionRequestFactory.build(
                type=SessionType.OAUTH,
                provider=AuthProviderName.GOOGLE,
                credential="google-id-token-xyz",
                invite_id="invite-token-no-inviter",
            )

            user = UserFactory.build()
            auth_service.sign_in_with_provider.return_value = OAuthSignInResult(
                outcome=AuthOutcome.CREATED,
                access_token="acc-oauth-new",
                refresh_token="ref-oauth-new",
                user=user,
            )

            invite_service.get_preview_metadata.return_value = InvitePreviewResponseFactory.build(
                club_slug="canterlot-club",
                club_name="Canterlot Club",
                join_policy=JoinPolicy.PUBLIC,
                invite_type=InviteType.PUBLIC,
                invited_by_username=None,
            )

            result = await use_case.execute(payload)

            assert result.is_new_user is True
            auth_service.attribute_referral.assert_not_called()
            email_dispatch_service.dispatch.assert_awaited_once()
