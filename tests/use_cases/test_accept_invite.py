import re
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import ClubOnboarding
from canterlot.exceptions import MemberBannedError
from canterlot.factories import UserFactory
from canterlot.types import ClubOnboardingStatus
from canterlot.use_cases.accept_invite import AcceptInviteUseCase

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


@pytest.fixture
def use_case(
    invite_service: AsyncMock,
    club_service: AsyncMock,
) -> AcceptInviteUseCase:
    return AcceptInviteUseCase(
        invite_service=invite_service,
        club_service=club_service,
    )


def describe_accept_invite_use_case():
    async def it_accepts_invite_admits_user_and_registers_usage_when_joined(
        use_case: AcceptInviteUseCase,
        invite_service: AsyncMock,
        club_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID)

        mock_invite = AsyncMock()
        mock_invite.club_id = SOME_CLUB_ID
        mock_invite.is_direct = True
        invite_service.validate_incoming_invite.return_value = mock_invite

        onboarding = ClubOnboarding(
            club_name="Canterlot Book Club",
            status=ClubOnboardingStatus.JOINED,
        )
        club_service.admit_user.return_value = onboarding

        result = await use_case.execute(invite_id="invite-token-123", current_user=user)

        assert result == onboarding
        invite_service.validate_incoming_invite.assert_awaited_once_with(
            invite_id="invite-token-123",
            user_email=user.email,
        )
        club_service.admit_user.assert_awaited_once_with(
            club_id=SOME_CLUB_ID,
            user_id=user.id,
            is_direct=True,
        )
        invite_service.register_invite_usage.assert_awaited_once_with("invite-token-123")

    async def it_registers_usage_when_status_is_pending_approval(
        use_case: AcceptInviteUseCase,
        invite_service: AsyncMock,
        club_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID)

        mock_invite = AsyncMock()
        mock_invite.club_id = SOME_CLUB_ID
        mock_invite.is_direct = False
        invite_service.validate_incoming_invite.return_value = mock_invite

        onboarding = ClubOnboarding(
            club_name="Canterlot Book Club",
            status=ClubOnboardingStatus.PENDING_APPROVAL,
        )
        club_service.admit_user.return_value = onboarding

        result = await use_case.execute(invite_id="invite-token-456", current_user=user)

        assert result == onboarding
        invite_service.register_invite_usage.assert_awaited_once_with("invite-token-456")

    async def it_raises_member_banned_error_when_status_is_banned(
        use_case: AcceptInviteUseCase,
        invite_service: AsyncMock,
        club_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID)

        mock_invite = AsyncMock()
        mock_invite.club_id = SOME_CLUB_ID
        mock_invite.is_direct = False
        invite_service.validate_incoming_invite.return_value = mock_invite

        onboarding = ClubOnboarding(
            club_name="Canterlot Book Club",
            status=ClubOnboardingStatus.BANNED,
        )
        club_service.admit_user.return_value = onboarding

        expected_msg = re.escape("This user is banned from this club.")
        with pytest.raises(MemberBannedError, match=expected_msg):
            await use_case.execute(invite_id="invite-token-789", current_user=user)

        invite_service.register_invite_usage.assert_not_called()

    async def it_returns_onboarding_without_registering_usage_when_already_member(
        use_case: AcceptInviteUseCase,
        invite_service: AsyncMock,
        club_service: AsyncMock,
    ):
        user = UserFactory.build(id=SOME_USER_ID)

        mock_invite = AsyncMock()
        mock_invite.club_id = SOME_CLUB_ID
        mock_invite.is_direct = False
        invite_service.validate_incoming_invite.return_value = mock_invite

        onboarding = ClubOnboarding(
            club_name="Canterlot Book Club",
            status=ClubOnboardingStatus.ALREADY_MEMBER,
        )
        club_service.admit_user.return_value = onboarding

        result = await use_case.execute(invite_id="invite-token-999", current_user=user)

        assert result == onboarding
        invite_service.register_invite_usage.assert_not_called()
