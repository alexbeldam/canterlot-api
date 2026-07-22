from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import SpikeActionContext
from canterlot.factories import ClubFactory, UserFactory
from canterlot.factories.base import MemberFactory
from canterlot.models.club import MemberSchema
from canterlot.services.dispatch import BatchEmailDispatchItem
from canterlot.types import MemberRole
from canterlot.use_cases.dissolve_club import DissolveClubUseCase

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    user_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> DissolveClubUseCase:
    return DissolveClubUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch_service,
    )


def describe_dissolve_club_use_case():
    async def it_dissolves_club_without_members_to_notify(
        use_case: DissolveClubUseCase,
        club_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        owner = UserFactory.build(id=SOME_USER_ID)
        club = ClubFactory.build(
            id=SOME_CLUB_ID,
            members=[MemberFactory.build(user_id=owner.id, role=MemberRole.OWNER)],
        )

        await use_case.execute(club, owner)

        user_service.get_by_ids.assert_not_called()
        club_service.dissolve_club.assert_awaited_once_with(
            club=club,
            caller_id=owner.id,
        )
        email_dispatch_service.dispatch_batch.assert_not_called()

    async def it_dissolves_club_and_batch_dispatches_notifications_to_other_members(
        use_case: DissolveClubUseCase,
        club_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        uid = PydanticObjectId("507f1f77bcf86cd799439011")
        uid1 = PydanticObjectId("507f1f77bcf86cd799439022")
        uid2 = PydanticObjectId("507f1f77bcf86cd799439033")

        owner = UserFactory.build(id=uid)
        other_user_1 = UserFactory.build(
            id=uid1,
            name="Twilight Sparkle",
            username="twilight",
            email="twilight@canterlot.dev",
        )
        other_user_2 = UserFactory.build(
            id=uid2,
            name="Rarity",
            username="rarity",
            email="rarity@canterlot.dev",
        )

        club = ClubFactory.build(
            id=SOME_CLUB_ID,
            members=[
                MemberSchema(user_id=uid),
                MemberSchema(user_id=uid1),
                MemberSchema(user_id=uid2),
            ],
        )

        user_service.get_by_ids.return_value = [other_user_1, other_user_2]

        await use_case.execute(club, owner)

        user_service.get_by_ids.assert_awaited_once_with([other_user_1.id, other_user_2.id])
        club_service.dissolve_club.assert_awaited_once_with(
            club=club,
            caller_id=owner.id,
        )

        email_dispatch_service.dispatch_batch.assert_awaited_once()
        batch_items = email_dispatch_service.dispatch_batch.call_args[0][0]
        assert len(batch_items) == 2

        item1, item2 = batch_items
        assert isinstance(item1, BatchEmailDispatchItem)
        assert isinstance(item1.task, EmailTaskPayload)
        assert item1.task.to == "twilight@canterlot.dev"
        assert item1.task.club_id == club.id
        assert isinstance(item1.task.context, SpikeActionContext)
        assert item1.prefs == other_user_1.email_preferences

        assert isinstance(item2, BatchEmailDispatchItem)
        assert item2.task.to == "rarity@canterlot.dev"
        assert item2.task.club_id == club.id
        assert isinstance(item2.task.context, SpikeActionContext)
        assert item2.prefs == other_user_2.email_preferences
