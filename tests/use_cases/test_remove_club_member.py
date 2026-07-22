from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import SpikeBaseContext
from canterlot.factories import ClubFactory, UserFactory
from canterlot.use_cases.remove_club_member import RemoveClubMemberUseCase

REMOVER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_TARGET_USER_ID = PydanticObjectId("507f1f77bcf86cd799439099")


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> RemoveClubMemberUseCase:
    return RemoveClubMemberUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch_service,
    )


def describe_remove_club_member_use_case():
    async def it_removes_member_and_dispatches_notification(
        use_case: RemoveClubMemberUseCase,
        club_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        target_user = UserFactory.build(id=SOME_TARGET_USER_ID, email="twilight@canterlot.dev")

        await use_case.execute(
            club=club,
            remover_id=REMOVER_ID,
            target_user=target_user,
        )

        club_service.remove_member.assert_awaited_once_with(
            club=club,
            remover_id=REMOVER_ID,
            target_user_id=target_user.id,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.to == "twilight@canterlot.dev"
        assert task.club_id is None
        assert isinstance(task.context, SpikeBaseContext)
        assert call_kwargs["prefs"] == target_user.email_preferences
