from beanie import PydanticObjectId

from canterlot.models import InviteModel, InviteType
from canterlot.repositories import InviteRepository
from canterlot.utils.format import NormalizedEmailStr


class BeanieInviteRepository(InviteRepository):
    async def find_by_id(self, invite_id: str) -> InviteModel | None:
        return await InviteModel.get(invite_id)

    async def find_one_active_public_by_club_id(self, club_id: PydanticObjectId) -> InviteModel | None:
        return await InviteModel.find_one(
            InviteModel.club_id == club_id,
            InviteModel.type == InviteType.PUBLIC,
            InviteModel.is_active == True,
        )

    async def find_by_club_id(self, club_id: PydanticObjectId) -> list[InviteModel]:
        return await InviteModel.find(InviteModel.club_id == club_id).to_list()

    async def save(self, invite: InviteModel) -> InviteModel:
        return await invite.save()

    async def increment_uses_count_by_id(self, invite_id: str) -> None:
        await InviteModel.find_one(InviteModel.id == invite_id).inc({InviteModel.uses_count: 1})

    async def deactivate_by_id(self, invite_id: str) -> None:
        await InviteModel.find_one(InviteModel.id == invite_id).set({InviteModel.is_active: False})

    async def deactivate_all_public_by_club_id(self, club_id: PydanticObjectId) -> None:
        await InviteModel.find(
            InviteModel.club_id == club_id,
            InviteModel.type == InviteType.PUBLIC,
            InviteModel.is_active == True,
        ).update_many({"$set": {InviteModel.is_active: False}})

    async def dactivate_all_direct_by_club_id_and_target_email(
        self,
        club_id: PydanticObjectId,
        target_email: NormalizedEmailStr,
    ) -> None:
        await InviteModel.find(
            InviteModel.club_id == club_id,
            InviteModel.target_email == target_email,
            InviteModel.type == InviteType.DIRECT,
            InviteModel.is_active == True,
        ).update_many({"$set": {InviteModel.is_active: False}})
