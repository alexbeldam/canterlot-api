from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import SpikeActionContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import BatchEmailDispatchItem, EmailDispatchService
from canterlot.services.user import UserService


class DissolveClubUseCase:
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
        owner: UserModel,
    ) -> None:
        owner_id = PydanticObjectId(owner.id)

        # ---------------------------------------------------------
        # 1. Resolve All Other Club Members
        # ---------------------------------------------------------
        other_members = [m for m in club.members if m.user_id != owner_id]
        member_ids = [m.user_id for m in other_members]
        member_users = await self.__user_service.get_by_ids(member_ids) if member_ids else []

        # ---------------------------------------------------------
        # 2. Execute Dissolution
        # ---------------------------------------------------------
        await self.__club_service.dissolve_club(
            club=club,
            caller_id=owner_id,
        )

        # ---------------------------------------------------------
        # 3. Batch Dispatch dissolution notification to All Members
        # ---------------------------------------------------------
        if member_users:
            batch_items = []
            club_id = PydanticObjectId(club.id)

            for member in member_users:
                context = SpikeActionContext.from_domain(
                    recipient=member,
                    club=club,
                    action_path="/clubs",
                )
                task = EmailTaskPayload(
                    template=Templates.SPIKE_CLUB_DISSOLVED,
                    to=member.email,
                    context=context,
                    club_id=club_id,
                )
                batch_items.append(BatchEmailDispatchItem(task=task, prefs=member.email_preferences))

            await self.__email_dispatch.dispatch_batch(batch_items)
