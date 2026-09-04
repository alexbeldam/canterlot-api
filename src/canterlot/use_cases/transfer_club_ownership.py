from beanie import PydanticObjectId

from canterlot.dto.club import OwnershipTransferRequest, OwnershipTransferResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import ClubActorActionContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import BatchEmailDispatchItem, EmailDispatchService
from canterlot.services.user import UserService


class TransferClubOwnershipUseCase:
    def __init__(
        self,
        club_service: ClubService,
        user_service: UserService,
        email_dispatch: EmailDispatchService,
    ):
        self.__club_service = club_service
        self.__user_service = user_service
        self.__email_dispatch = email_dispatch

    async def execute(
        self,
        club: ClubModel,
        current_owner: UserModel,
        payload: OwnershipTransferRequest,
    ) -> OwnershipTransferResponse:
        current_owner_id = PydanticObjectId(current_owner.id)

        # ---------------------------------------------------------
        # 1. Execute Ownership Transfer
        # ---------------------------------------------------------
        reclaim_deadline = await self.__club_service.transfer_ownership(
            club=club,
            current_owner_id=current_owner_id,
            target_username=payload.new_owner_username,
        )

        # ---------------------------------------------------------
        # 2. Resolve New Owner User Model
        # ---------------------------------------------------------
        new_owner = await self.__user_service.get_by_username(payload.new_owner_username)

        # ---------------------------------------------------------
        # 3. Build Batch Payload (New Owner + Former Owner)
        # ---------------------------------------------------------
        # Email 1: Notify New Owner
        new_owner_task = EmailTaskPayload(
            template=Templates.CELESTIA_OWNERSHIP_RECEIVED,
            to=new_owner.email,
            context=ClubActorActionContext.from_domain(
                recipient=new_owner,
                actor=current_owner,
                club=club,
            ),
        )

        # Email 2: Confirm to Former Owner
        former_owner_task = EmailTaskPayload(
            template=Templates.LUNA_OWNERSHIP_TRANSFERRED,
            to=current_owner.email,
            context=ClubActorActionContext.from_domain(
                recipient=current_owner,
                actor=current_owner,
                club=club,
            ),
        )

        batch_items = [
            BatchEmailDispatchItem(task=new_owner_task, prefs=new_owner.email_preferences),
            BatchEmailDispatchItem(task=former_owner_task, prefs=current_owner.email_preferences),
        ]

        # ---------------------------------------------------------
        # 4. Dispatch Batch
        # ---------------------------------------------------------
        await self.__email_dispatch.dispatch_batch(batch_items)

        return OwnershipTransferResponse(reclaim_deadline=reclaim_deadline)
