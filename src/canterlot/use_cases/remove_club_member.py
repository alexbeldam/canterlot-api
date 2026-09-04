from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import SpikeBaseContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import EmailDispatchService


class RemoveClubMemberUseCase:
    def __init__(
        self,
        club_service: ClubService,
        email_dispatch: EmailDispatchService,
    ):
        self.__club_service = club_service
        self.__email_dispatch = email_dispatch

    async def execute(
        self,
        club: ClubModel,
        remover_id: PydanticObjectId,
        target_user: UserModel,
    ) -> None:
        target_user_id = PydanticObjectId(target_user.id)

        # ---------------------------------------------------------
        # 1. Execute Member Removal & Ban
        # ---------------------------------------------------------
        await self.__club_service.remove_member(
            club=club,
            remover_id=remover_id,
            target_user_id=target_user_id,
        )

        # ---------------------------------------------------------
        # 2. Dispatch notification to target user
        # ---------------------------------------------------------
        context = SpikeBaseContext.from_domain(
            recipient=target_user,
            club=club,
        )

        task = EmailTaskPayload(
            template=Templates.SPIKE_REMOVED,
            to=target_user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=target_user.email_preferences,
        )
