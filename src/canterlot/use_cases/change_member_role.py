from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import SpikeRoleContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import MemberRole


class ChangeMemberRoleUseCase:
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
        caller_id: PydanticObjectId,
        target_user: UserModel,
        new_role: MemberRole,
    ) -> None:
        target_user_id = PydanticObjectId(target_user.id)

        # ---------------------------------------------------------
        # 1. Execute Member Role Change
        # ---------------------------------------------------------
        is_promotion = await self.__club_service.change_member_role(
            club=club,
            caller_id=caller_id,
            target_user_id=target_user_id,
            new_role=new_role,
        )

        # ---------------------------------------------------------
        # 2. Short-circuit if role was already identical
        # ---------------------------------------------------------
        if is_promotion is None:
            return

        # ---------------------------------------------------------
        # 3. Dispatch notification to target user
        # ---------------------------------------------------------
        context = SpikeRoleContext.from_domain(
            recipient=target_user,
            club=club,
            role_name=new_role,
            is_promotion=is_promotion,
        )

        task = EmailTaskPayload(
            template=Templates.SPIKE_ROLE_CHANGED,
            to=target_user.email,
            context=context,
            club_id=PydanticObjectId(club.id),
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=target_user.email_preferences,
        )
