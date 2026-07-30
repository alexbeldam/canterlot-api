from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.models.club import MemberSchema
from canterlot.types import MemberRole
from canterlot.use_cases.reclaim_ownership_transfer import ReclaimClubOwnershipUseCase
from tools.factories import ClubFactory, UserFactory


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    user_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> ReclaimClubOwnershipUseCase:
    return ReclaimClubOwnershipUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch_service,
    )


def describe_reclaim_club_ownership_use_case():
    async def it_reclaims_ownership_and_dispatches_email_to_demoted_owner(
        use_case: ReclaimClubOwnershipUseCase,
        club_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        reclaiming_id = PydanticObjectId("507f1f77bcf86cd799439011")
        reclaiming_owner = UserFactory.build(id=reclaiming_id, name="Twilight Sparkle")
        demoted_owner_id = PydanticObjectId("507f1f77bcf86cd799439022")
        demoted_owner = UserFactory.build(
            id=demoted_owner_id,
            name="Spike",
            username="spike",
            email="spike@canterlot.dev",
        )

        user_service.get_by_id.return_value = demoted_owner

        club = ClubFactory.build(
            members=[
                MemberSchema(user_id=demoted_owner_id, role=MemberRole.OWNER),
                MemberSchema(user_id=reclaiming_id, role=MemberRole.ADMIN),
            ]
        )

        await use_case.execute(club=club, reclaiming_owner=reclaiming_owner)

        user_service.get_by_id.assert_awaited_once_with(demoted_owner_id)
        club_service.reclaim_ownership.assert_awaited_once_with(
            club=club,
            caller_id=reclaiming_owner.id,
        )

        email_dispatch_service.dispatch.assert_awaited_once()
        call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
        task = call_kwargs["task"]

        assert isinstance(task, EmailTaskPayload)
        assert task.template == Templates.LUNA_OWNERSHIP_RECLAIMED
        assert task.to == "spike@canterlot.dev"
        assert task.context.recipient_name == "Spike"
        assert task.context.actor_name == "Twilight Sparkle"

    async def it_reclaims_ownership_without_sending_email_if_no_current_owner_in_club(
        use_case: ReclaimClubOwnershipUseCase,
        club_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        reclaiming_id = PydanticObjectId("507f1f77bcf86cd799439011")
        reclaiming_owner = UserFactory.build(id=reclaiming_id)
        club = ClubFactory.build(
            members=[
                MemberSchema(user_id=reclaiming_id, role=MemberRole.ADMIN),
            ]
        )

        await use_case.execute(club=club, reclaiming_owner=reclaiming_owner)

        user_service.get_by_id.assert_not_called()
        club_service.reclaim_ownership.assert_awaited_once_with(
            club=club,
            caller_id=reclaiming_owner.id,
        )
        email_dispatch_service.dispatch.assert_not_called()
