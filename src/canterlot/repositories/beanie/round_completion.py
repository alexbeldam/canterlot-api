from datetime import datetime
from typing import cast

from beanie import PydanticObjectId
from beanie.operators import In
from pydantic import BaseModel
from pymongo.results import UpdateResult

from canterlot.hoodie import transactional
from canterlot.models import RoundCompletionModel, RoundModel
from canterlot.repositories import CompletionResult, RoundCompletionRepository
from canterlot.types import RoundStatus


class UserIdProjection(BaseModel):
    user_id: PydanticObjectId


class BeanieRoundCompletionRepository(RoundCompletionRepository):
    async def find_user_ids_by_round_id(self, round_id: PydanticObjectId) -> set[PydanticObjectId]:
        projections = (
            await RoundCompletionModel.find(RoundCompletionModel.round_id == round_id)
            .project(UserIdProjection)
            .to_list()
        )

        return {projection.user_id for projection in projections}

    @transactional
    async def record_completion(
        self,
        club_id: PydanticObjectId,
        round_id: PydanticObjectId,
        book_id: PydanticObjectId,
        user_id: PydanticObjectId,
        completed_at: datetime,
        current_member_ids: set[PydanticObjectId],
    ) -> CompletionResult:
        insert_result = await RoundCompletionModel.find_one(
            RoundCompletionModel.round_id == round_id,
            RoundCompletionModel.user_id == user_id,
        ).update_one(
            {
                "$setOnInsert": {
                    "club_id": club_id,
                    "round_id": round_id,
                    "book_id": book_id,
                    "user_id": user_id,
                    "completed_at": completed_at,
                }
            },
            upsert=True,
        )
        is_new = cast(UpdateResult, insert_result).upserted_id is not None
        if not is_new:
            return CompletionResult(is_new=False, round_concluded=False)

        # Written before counting (not after) so concurrent finishers serialize on this
        # transaction conflict instead of racing the count below.
        lock_result = await RoundModel.find_one(
            RoundModel.id == round_id,
            RoundModel.status == RoundStatus.DECIDED,
        ).update_one(
            {"$set": {"last_completed_by": user_id, "last_completed_at": completed_at}},
        )
        if cast(UpdateResult, lock_result).matched_count == 0:
            return CompletionResult(is_new=True, round_concluded=False)

        finisher_count = await RoundCompletionModel.find(
            RoundCompletionModel.round_id == round_id,
            In(RoundCompletionModel.user_id, list(current_member_ids)),
        ).count()
        if finisher_count < len(current_member_ids):
            return CompletionResult(is_new=True, round_concluded=False)

        conclude_result = await RoundModel.find_one(
            RoundModel.id == round_id,
            RoundModel.status == RoundStatus.DECIDED,
        ).update_one({"$set": {"status": RoundStatus.CONCLUDED}})

        return CompletionResult(is_new=True, round_concluded=cast(UpdateResult, conclude_result).matched_count > 0)

    async def find_majority_excluded_book_ids(
        self,
        club_id: PydanticObjectId,
        current_member_ids: set[PydanticObjectId],
    ) -> set[PydanticObjectId]:
        results = (
            await RoundCompletionModel.find(RoundCompletionModel.club_id == club_id)
            .aggregate(
                [
                    {
                        "$group": {
                            "_id": "$round_id",
                            "book_id": {"$first": "$book_id"},
                            "total_finishers": {"$sum": 1},
                            "current_finishers": {
                                "$sum": {"$cond": [{"$in": ["$user_id", list(current_member_ids)]}, 1, 0]}
                            },
                        }
                    },
                    {"$match": {"$expr": {"$gt": ["$current_finishers", {"$divide": ["$total_finishers", 2]}]}}},
                    {"$group": {"_id": None, "book_ids": {"$addToSet": "$book_id"}}},
                ]
            )
            .to_list()
        )

        return set(results[0]["book_ids"]) if results else set()
