from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import OwnershipTransferRequest, OwnershipTransferResponse
from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import ClubActorActionContext
from canterlot.services.dispatch import BatchEmailDispatchItem
from canterlot.use_cases.transfer_club_ownership import TransferClubOwnershipUseCase
from tools.factories import ClubFactory, UserFactory


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    user_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> TransferClubOwnershipUseCase:
    return TransferClubOwnershipUseCase(
        club_service=club_service,
        user_service=user_service,
        email_dispatch=email_dispatch_service,
    )


def describe_transfer_club_ownership_use_case():
    async def it_transfers_ownership_and_dispatches_batch_notifications(
        use_case: TransferClubOwnershipUseCase,
        club_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        current_owner = UserFactory.build(
            id=PydanticObjectId("507f1f77bcf86cd799439011"), email="celestia@canterlot.dev"
        )
        new_owner = UserFactory.build(
            id=PydanticObjectId("507f1f77bcf86cd799439099"),
            name="Twilight Sparkle",
            username="twilight",
            email="twilight@canterlot.dev",
        )
        club = ClubFactory.build(id=PydanticObjectId("507f1f77bcf86cd799439012"))
        payload = OwnershipTransferRequest(new_owner_username="twilight")

        reclaim_deadline = datetime.now(UTC) + timedelta(hours=24)
        club_service.transfer_ownership.return_value = reclaim_deadline
        user_service.get_by_username.return_value = new_owner

        response = await use_case.execute(club, current_owner, payload)

        assert isinstance(response, OwnershipTransferResponse)
        assert response.reclaim_deadline == reclaim_deadline

        club_service.transfer_ownership.assert_awaited_once_with(
            club=club,
            current_owner_id=current_owner.id,
            target_username="twilight",
        )
        user_service.get_by_username.assert_awaited_once_with("twilight")

        email_dispatch_service.dispatch_batch.assert_awaited_once()
        batch_items = email_dispatch_service.dispatch_batch.call_args[0][0]
        assert len(batch_items) == 2

        new_owner_item, former_owner_item = batch_items

        assert isinstance(new_owner_item, BatchEmailDispatchItem)
        assert isinstance(new_owner_item.task, EmailTaskPayload)
        assert new_owner_item.task.to == "twilight@canterlot.dev"
        assert isinstance(new_owner_item.task.context, ClubActorActionContext)
        assert new_owner_item.prefs == new_owner.email_preferences

        assert isinstance(former_owner_item, BatchEmailDispatchItem)
        assert isinstance(former_owner_item.task, EmailTaskPayload)
        assert former_owner_item.task.to == "celestia@canterlot.dev"
        assert isinstance(former_owner_item.task.context, ClubActorActionContext)
        assert former_owner_item.prefs == current_owner.email_preferences
