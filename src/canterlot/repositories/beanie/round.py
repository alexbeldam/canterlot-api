from datetime import datetime
from typing import cast

from beanie import PydanticObjectId
from pymongo.results import UpdateResult

from canterlot.models import BookModel, RoundModel
from canterlot.models.round import ACTIVE_ROUND_STATUSES
from canterlot.repositories import RoundRepository
from canterlot.types import RoundResolutionMethod, RoundStatus


class BeanieRoundRepository(RoundRepository):
    async def find_active_by_club_id(self, club_id: PydanticObjectId) -> RoundModel | None:
        return await RoundModel.find_one(
            RoundModel.club.id == club_id,
            {"status": {"$in": list(ACTIVE_ROUND_STATUSES)}},
        )

    async def save(self, round_: RoundModel) -> RoundModel:
        return await round_.save()

    async def finalize_with_draw(
        self,
        round_id: PydanticObjectId,
        book_id: PydanticObjectId,
        decided_at: datetime,
        deadline: datetime | None,
    ) -> bool:
        # deadline is omitted from $set (not set to None) when there's no pending duration to
        # resolve, so an already-stored custom deadline from creation time is never clobbered.
        update_fields: dict[str, object] = {
            "status": RoundStatus.DECIDED,
            "resolution_method": RoundResolutionMethod.DRAW,
            "book": BookModel.link_from_id(book_id).to_ref(),
            "decided_at": decided_at,
        }
        if deadline is not None:
            update_fields["deadline"] = deadline

        result = await RoundModel.find_one(
            RoundModel.id == round_id,
            RoundModel.status == RoundStatus.SETUP,
        ).update_one({"$set": update_fields})

        return cast(UpdateResult, result).matched_count > 0

    async def finalize_with_vote(self, round_id: PydanticObjectId) -> bool:
        result = await RoundModel.find_one(
            RoundModel.id == round_id,
            RoundModel.status == RoundStatus.SETUP,
        ).update_one(
            {
                "$set": {
                    "status": RoundStatus.VOTING,
                    "resolution_method": RoundResolutionMethod.VOTE,
                }
            }
        )

        return cast(UpdateResult, result).matched_count > 0
