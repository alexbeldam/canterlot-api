from beanie import PydanticObjectId

from canterlot.dto.club import ClubOnboarding
from canterlot.exceptions import MemberBannedError
from canterlot.models.user import UserModel
from canterlot.services.club import ClubService
from canterlot.services.invite import InviteService
from canterlot.types import ClubOnboardingStatus


class AcceptInviteUseCase:
    def __init__(
        self,
        invite_service: InviteService,
        club_service: ClubService,
    ):
        self.__invite_service = invite_service
        self.__club_service = club_service

    async def execute(
        self,
        invite_id: str,
        current_user: UserModel,
    ) -> ClubOnboarding:
        # ---------------------------------------------------------
        # 1. Validate Incoming Invite
        # ---------------------------------------------------------
        validated_invite = await self.__invite_service.validate_incoming_invite(
            invite_id=invite_id,
            user_email=current_user.email,
        )

        # ---------------------------------------------------------
        # 2. Admit User to Club
        # ---------------------------------------------------------
        onboarding = await self.__club_service.admit_user(
            club_id=validated_invite.club_id,
            user_id=PydanticObjectId(current_user.id),
            is_direct=validated_invite.is_direct,
        )

        # ---------------------------------------------------------
        # 3. Handle Banned Status & Record Usage
        # ---------------------------------------------------------
        if onboarding.status == ClubOnboardingStatus.BANNED:
            raise MemberBannedError("This user is banned from this club.")

        if onboarding.status in [ClubOnboardingStatus.JOINED, ClubOnboardingStatus.PENDING_APPROVAL]:
            await self.__invite_service.register_invite_usage(invite_id)

        return onboarding
