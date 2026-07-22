from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import ClubActionContext
from canterlot.models.club import ClubModel
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.dispatch import EmailDispatchService


class ApprovePendingMemberUseCase:
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
        reviewer_id: PydanticObjectId,
        target_user: UserModel,
    ) -> None:
        club_id = PydanticObjectId(club.id)

        # ---------------------------------------------------------
        # 1. Review and approve pending request
        # ---------------------------------------------------------
        await self.__club_service.review_pending_request(
            club_id=club_id,
            reviewer_id=reviewer_id,
            target_user_id=PydanticObjectId(target_user.id),
            approve=True,
        )

        # ---------------------------------------------------------
        # 1. Dispatch notification to target user
        # ---------------------------------------------------------
        context = ClubActionContext.from_domain(
            recipient=target_user,
            club=club,
        )

        task = EmailTaskPayload(
            template=Templates.CELESTIA_APPROVED,
            to=target_user.email,
            context=context,
            club_id=club_id,
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=target_user.email_preferences,
        )
