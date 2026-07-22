# use_cases/reclaim_club_ownership.py
from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import ClubActorActionContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.services.user import UserService
from canterlot.types import MemberRole


class ReclaimClubOwnershipUseCase:
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
        reclaiming_owner: UserModel,
    ) -> None:
        reclaiming_owner_id = PydanticObjectId(reclaiming_owner.id)

        # ---------------------------------------------------------
        # 1. Resolve Current Owner (Target receiving demotion)
        # ---------------------------------------------------------
        demoted_owner_schema = next((m for m in club.members if m.role == MemberRole.OWNER), None)
        demoted_owner_user = None
        if demoted_owner_schema:
            demoted_owner_user = await self.__user_service.get_by_id(demoted_owner_schema.user_id)

        # ---------------------------------------------------------
        # 2. Execute Ownership Reclaim
        # ---------------------------------------------------------
        await self.__club_service.reclaim_ownership(
            club=club,
            caller_id=reclaiming_owner_id,
        )

        # ---------------------------------------------------------
        # 3. Dispatch Notification Email to Demoted User
        # ---------------------------------------------------------
        if demoted_owner_user:
            context = ClubActorActionContext.from_domain(
                recipient=demoted_owner_user,
                actor=reclaiming_owner,
                club=club,
            )

            task = EmailTaskPayload(
                template=Templates.LUNA_OWNERSHIP_RECLAIMED,
                to=demoted_owner_user.email,
                context=context,
            )

            await self.__email_dispatch.dispatch(
                task=task,
                prefs=demoted_owner_user.email_preferences,
            )
