from datetime import datetime
from typing import cast

from beanie import Link, PydanticObjectId
from beanie.operators import In, Set
from pydantic import BaseModel
from pymongo.results import UpdateResult

from canterlot.hoodie import TransactionError, link_id, transactional
from canterlot.models import ClubMembershipModel, ClubModel, UserModel
from canterlot.repositories import ClubMembershipRepository
from canterlot.types import MemberRole, MembershipStatus

_ACTIVE_STATUSES = [MembershipStatus.OWNER, MembershipStatus.ADMIN, MembershipStatus.MEMBER]
_PROMOTABLE_STATUSES = [MembershipStatus.ADMIN, MembershipStatus.MEMBER]


class UserLinkProjection(BaseModel):
    user: Link[UserModel]


class StatusProjection(BaseModel):
    status: MembershipStatus


class MembershipConflict(TransactionError):
    pass


class BeanieClubMembershipRepository(ClubMembershipRepository):
    async def find_member_role_by_club_id_and_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> MemberRole | None:
        projection = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
            In(ClubMembershipModel.status, _ACTIVE_STATUSES),
        ).project(StatusProjection)

        return MemberRole(projection.status.value) if projection else None

    async def exists_by_club_id_and_member_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> bool:
        return await ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
            In(ClubMembershipModel.status, _ACTIVE_STATUSES),
        ).exists()

    async def exists_by_club_id_and_pending_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> bool:
        return await ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
            ClubMembershipModel.status == MembershipStatus.PENDING,
        ).exists()

    async def exists_by_club_id_and_banned_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> bool:
        return await ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
            ClubMembershipModel.status == MembershipStatus.BANNED,
        ).exists()

    async def upsert_member(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
        role: MemberRole,
        joined_at: datetime,
    ) -> None:
        status = MembershipStatus(role.value)
        await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
        ).upsert(
            Set(
                {
                    ClubMembershipModel.status: status,
                    ClubMembershipModel.joined_at: joined_at,
                    ClubMembershipModel.requested_at: None,
                }
            ),
            on_insert=ClubMembershipModel(
                club=ClubModel.link_from_id(club_id),
                user=UserModel.link_from_id(user_id),
                status=status,
                joined_at=joined_at,
            ),
        )

    async def create_pending_request(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
        requested_at: datetime,
    ) -> None:
        await ClubMembershipModel(
            club=ClubModel.link_from_id(club_id),
            user=UserModel.link_from_id(user_id),
            status=MembershipStatus.PENDING,
            requested_at=requested_at,
        ).insert()

    async def delete_membership(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
        ).delete()

    async def ban_member(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus.BANNED}))

    async def change_member_role(
        self,
        club_id: PydanticObjectId,
        member_id: PydanticObjectId,
        new_role: MemberRole,
    ) -> bool:
        result = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == member_id,
            In(ClubMembershipModel.status, _PROMOTABLE_STATUSES),
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus(new_role.value)}))

        return cast(UpdateResult, result).matched_count > 0

    @transactional(on_conflict=False)
    async def transfer_ownership(
        self,
        club_id: PydanticObjectId,
        current_owner_id: PydanticObjectId,
        new_owner_id: PydanticObjectId,
        transferred_at: datetime,
    ) -> bool:
        promoted = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == new_owner_id,
            In(ClubMembershipModel.status, _PROMOTABLE_STATUSES),
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus.OWNER}))
        if cast(UpdateResult, promoted).matched_count == 0:
            raise MembershipConflict

        demoted = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == current_owner_id,
            ClubMembershipModel.status == MembershipStatus.OWNER,
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus.ADMIN}))
        if cast(UpdateResult, demoted).matched_count == 0:
            raise MembershipConflict

        club_updated = await ClubModel.find_one(ClubModel.id == club_id).update_one(
            {
                "$set": {
                    "ownership_transferred_at": transferred_at,
                    "protected_former_owner_id": current_owner_id,
                }
            },
        )
        if cast(UpdateResult, club_updated).matched_count == 0:
            raise MembershipConflict

        return True

    @transactional(on_conflict=False)
    async def reclaim_ownership(
        self,
        club_id: PydanticObjectId,
        former_owner_id: PydanticObjectId,
        current_owner_id: PydanticObjectId,
    ) -> bool:
        reclaimed = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == former_owner_id,
            ClubMembershipModel.status == MembershipStatus.ADMIN,
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus.OWNER}))
        if cast(UpdateResult, reclaimed).matched_count == 0:
            raise MembershipConflict

        demoted = await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == current_owner_id,
            ClubMembershipModel.status == MembershipStatus.OWNER,
        ).update_one(Set({ClubMembershipModel.status: MembershipStatus.ADMIN}))
        if cast(UpdateResult, demoted).matched_count == 0:
            raise MembershipConflict

        club_updated = await ClubModel.find_one(
            ClubModel.id == club_id,
            ClubModel.protected_former_owner_id == former_owner_id,
        ).update_one(
            {"$set": {"ownership_transferred_at": None, "protected_former_owner_id": None}},
        )
        if cast(UpdateResult, club_updated).matched_count == 0:
            raise MembershipConflict

        return True

    async def find_active_by_club_id(self, club_id: PydanticObjectId) -> list[ClubMembershipModel]:
        return await ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            In(ClubMembershipModel.status, _ACTIVE_STATUSES),
        ).to_list()

    async def find_active_membership_by_club_id_and_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> ClubMembershipModel | None:
        return await ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.user.id == user_id,
            In(ClubMembershipModel.status, _ACTIVE_STATUSES),
        )

    async def find_pending_by_club_id(self, club_id: PydanticObjectId) -> list[ClubMembershipModel]:
        return await ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.status == MembershipStatus.PENDING,
        ).to_list()

    async def find_active_member_ids_by_club_id(self, club_id: PydanticObjectId) -> list[PydanticObjectId]:
        query = ClubMembershipModel.find(
            ClubMembershipModel.club.id == club_id,
            In(ClubMembershipModel.status, _ACTIVE_STATUSES),
        )
        projections = await query.project(UserLinkProjection).to_list()

        return [link_id(projection.user) for projection in projections]

    async def find_owner_id_by_club_id(self, club_id: PydanticObjectId) -> PydanticObjectId | None:
        query = ClubMembershipModel.find_one(
            ClubMembershipModel.club.id == club_id,
            ClubMembershipModel.status == MembershipStatus.OWNER,
        )
        projection = await query.project(UserLinkProjection)

        return link_id(projection.user) if projection else None
