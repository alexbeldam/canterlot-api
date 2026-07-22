from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.dto.auth import RegisterResponse
from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import EmailVerificationContext
from canterlot.factories import ClubOnboardingFactory, UserFactory, UserRegisterRequestFactory
from canterlot.services.auth import RegisterResult
from canterlot.types import ClubOnboardingStatus, VerificationScope
from canterlot.use_cases.register_user import RegisterUserUseCase, RegisterUserUseCaseResult

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def use_case(
    auth_service: AsyncMock,
    invite_service: AsyncMock,
    club_service: AsyncMock,
    verification_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> RegisterUserUseCase:
    return RegisterUserUseCase(
        auth_service=auth_service,
        invite_service=invite_service,
        club_service=club_service,
        verification_service=verification_service,
        email_dispatch=email_dispatch_service,
    )


def describe_register_user_use_case():
    async def it_registers_a_user_without_an_invite(
        use_case: RegisterUserUseCase,
        auth_service: AsyncMock,
        invite_service: AsyncMock,
        club_service: AsyncMock,
        verification_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        payload = UserRegisterRequestFactory.build(
            name="Twilight Sparkle",
            username="twilight",
            email="twilight@canterlot.dev",
            password=SecretStr("securePassword123!"),
            terms_version=1,
            privacy_version=1,
        )

        user = UserFactory.build(id=SOME_USER_ID)
        auth_result = RegisterResult(
            user=user,
            access_token="access-token-123",
            refresh_token="refresh-token-456",
            token_type="bearer",
        )
        auth_service.register_user.return_value = auth_result
        verification_service.create_code.return_value = SecretStr("87654321")

        result = await use_case.execute(payload)

        assert isinstance(result, RegisterUserUseCaseResult)
        assert result.refresh_token == "refresh-token-456"
        assert isinstance(result.response, RegisterResponse)
        assert result.response.access_token == "access-token-123"
        assert result.response.onboarding is None

        invite_service.validate_incoming_invite.assert_not_called()
        club_service.admit_user.assert_not_called()
        invite_service.register_invite_usage.assert_not_called()

        auth_service.register_user.assert_awaited_once_with(payload, None)
        verification_service.create_code.assert_awaited_once_with(
            user_id=user.id,
            scope=VerificationScope.EMAIL,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task_arg = call_kwargs["task"]
        assert isinstance(task_arg, EmailTaskPayload)
        assert task_arg.to == user.email
        assert isinstance(task_arg.context, EmailVerificationContext)
        assert call_kwargs["prefs"] == user.email_preferences

    async def it_validates_invite_admits_user_and_records_invite_usage(
        use_case: RegisterUserUseCase,
        auth_service: AsyncMock,
        invite_service: AsyncMock,
        club_service: AsyncMock,
        verification_service: AsyncMock,
    ):
        payload = UserRegisterRequestFactory.build(
            name="Twilight Sparkle",
            username="twilight",
            email="twilight@canterlot.dev",
            password=SecretStr("securePassword123!"),
            terms_version=1,
            privacy_version=1,
            invite_id="invite-token-abc",
            invited_by="celestia",
        )

        mock_invite = AsyncMock()
        mock_invite.invited_by = "celestia_override"
        mock_invite.club_id = PydanticObjectId("507f1f77bcf86cd799439099")
        mock_invite.is_direct = True
        invite_service.validate_incoming_invite.return_value = mock_invite

        user = UserFactory.build(id=SOME_USER_ID)
        auth_result = RegisterResult(
            user=user,
            access_token="access-token-123",
            refresh_token="refresh-token-456",
            token_type="bearer",
        )
        auth_service.register_user.return_value = auth_result

        onboarding = ClubOnboardingFactory.build(club_name="Canterlot Book Club", status=ClubOnboardingStatus.JOINED)
        club_service.admit_user.return_value = onboarding

        verification_service.create_code.return_value = SecretStr("87654321")

        result = await use_case.execute(payload)

        assert result.response.onboarding == onboarding

        invite_service.validate_incoming_invite.assert_awaited_once_with(
            "invite-token-abc",
            "twilight@canterlot.dev",
            "celestia",
        )
        auth_service.register_user.assert_awaited_once_with(payload, "celestia_override")
        club_service.admit_user.assert_awaited_once_with(
            mock_invite.club_id,
            user.id,
            True,
        )
        invite_service.register_invite_usage.assert_awaited_once_with("invite-token-abc")

    async def it_skips_invite_usage_recording_if_onboarding_status_is_banned_or_already_member(
        use_case: RegisterUserUseCase,
        auth_service: AsyncMock,
        invite_service: AsyncMock,
        club_service: AsyncMock,
        verification_service: AsyncMock,
    ):
        payload = UserRegisterRequestFactory.build(
            name="Twilight Sparkle",
            username="twilight",
            email="twilight@canterlot.dev",
            password=SecretStr("securePassword123!"),
            terms_version=1,
            privacy_version=1,
            invite_id="invite-token-abc",
        )

        mock_invite = AsyncMock()
        mock_invite.invited_by = None
        mock_invite.club_id = PydanticObjectId("507f1f77bcf86cd799439099")
        mock_invite.is_direct = False
        invite_service.validate_incoming_invite.return_value = mock_invite

        user = UserFactory.build(id=SOME_USER_ID)
        auth_service.register_user.return_value = RegisterResult(
            user=user,
            access_token="token",
            refresh_token="ref",
            token_type="bearer",
        )

        onboarding = ClubOnboardingFactory.build(club_name="Canterlot Book Club", status=ClubOnboardingStatus.BANNED)
        club_service.admit_user.return_value = onboarding

        verification_service.create_code.return_value = SecretStr("87654321")

        await use_case.execute(payload)

        invite_service.register_invite_usage.assert_not_called()
