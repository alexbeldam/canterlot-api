from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import ClubActionContext
from canterlot.factories import ClubFactory, UserFactory
from canterlot.use_cases.approve_pending_member import ApprovePendingMemberUseCase

REVIEWER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_TARGET_USER_ID = PydanticObjectId("507f1f77bcf86cd799439099")


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> ApprovePendingMemberUseCase:
    return ApprovePendingMemberUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch_service,
    )


def describe_approve_pending_member_use_case():
    async def it_reviews_pending_request_and_dispatches_approval_notification(
        use_case: ApprovePendingMemberUseCase,
        club_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID, name="Canterlot Book Club")
        target_user = UserFactory.build(
            id=SOME_TARGET_USER_ID,
            name="Twilight Sparkle",
            email="twilight@canterlot.dev",
        )

        await use_case.execute(
            club=club,
            reviewer_id=REVIEWER_ID,
            target_user=target_user,
        )

        club_service.review_pending_request.assert_awaited_once_with(
            club_id=club.id,
            reviewer_id=REVIEWER_ID,
            target_user_id=target_user.id,
            approve=True,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.CELESTIA_APPROVED
        assert task.to == "twilight@canterlot.dev"
        assert task.club_id == club.id
        assert isinstance(task.context, ClubActionContext)
        assert task.context.recipient_name == "Twilight Sparkle"
        assert task.context.club_name == "Canterlot Book Club"
        assert call_kwargs["prefs"] == target_user.email_preferences
