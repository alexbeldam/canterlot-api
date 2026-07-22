from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails import EmailTaskPayload
from canterlot.emails.core.schemas import SpikeRoleContext
from canterlot.factories import ClubFactory, UserFactory
from canterlot.types import MemberRole
from canterlot.use_cases import ChangeMemberRoleUseCase

CALLER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_TARGET_USER_ID = PydanticObjectId("507f1f77bcf86cd799439099")


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> ChangeMemberRoleUseCase:
    return ChangeMemberRoleUseCase(
        club_service=club_service,
        email_dispatch=email_dispatch_service,
    )


def describe_change_member_role_use_case():
    async def it_short_circuits_when_role_is_already_identical(
        use_case: ChangeMemberRoleUseCase,
        club_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        target_user = UserFactory.build(id=SOME_TARGET_USER_ID)
        club_service.change_member_role.return_value = None

        await use_case.execute(
            club=club,
            caller_id=CALLER_ID,
            target_user=target_user,
            new_role=MemberRole.MEMBER,
        )

        club_service.change_member_role.assert_awaited_once_with(
            club=club,
            caller_id=CALLER_ID,
            target_user_id=target_user.id,
            new_role=MemberRole.MEMBER,
        )
        email_dispatch_service.dispatch.assert_not_called()

    @pytest.mark.parametrize("is_promotion", [True, False])
    async def it_executes_role_change_and_dispatches_notification(
        is_promotion: bool,
        use_case: ChangeMemberRoleUseCase,
        club_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        target_user = UserFactory.build(id=SOME_TARGET_USER_ID, email="twilight@canterlot.dev")
        club_service.change_member_role.return_value = is_promotion

        await use_case.execute(
            club=club,
            caller_id=CALLER_ID,
            target_user=target_user,
            new_role=MemberRole.ADMIN,
        )

        club_service.change_member_role.assert_awaited_once_with(
            club=club,
            caller_id=CALLER_ID,
            target_user_id=target_user.id,
            new_role=MemberRole.ADMIN,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.to == "twilight@canterlot.dev"
        assert task.club_id == club.id
        assert isinstance(task.context, SpikeRoleContext)
        assert call_kwargs["prefs"] == target_user.email_preferences
