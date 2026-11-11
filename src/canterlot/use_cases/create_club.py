from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest, ClubResponse
from canterlot.hoodie import link_id
from canterlot.services.club import ClubService
from canterlot.services.invite import InviteService


class CreateClubUseCase:
    def __init__(
        self,
        club_service: ClubService,
        invite_service: InviteService,
    ):
        self.__club_service = club_service
        self.__invite_service = invite_service

    async def execute(
        self,
        creator_id: PydanticObjectId,
        payload: ClubCreateRequest,
    ) -> ClubResponse:
        # ---------------------------------------------------------
        # 1. Create New Club Workspace
        # ---------------------------------------------------------
        club = await self.__club_service.create_new_club(
            creator_id=creator_id,
            data=payload,
        )

        # ---------------------------------------------------------
        # 2. Rotate Initial Public Invite Link
        # ---------------------------------------------------------
        await self.__invite_service.rotate_public_link(
            club_id=PydanticObjectId(club.id),
            user_id=creator_id,
        )

        # ---------------------------------------------------------
        # 3. Resolve Member Usernames & Return DTO
        # ---------------------------------------------------------
        active_members = await self.__club_service.get_active_members(PydanticObjectId(club.id))
        member_usernames = await self.__club_service.resolve_member_usernames(
            [link_id(member.user) for member in active_members]
        )

        return ClubResponse.from_model(club, active_members, user_usernames=member_usernames)
