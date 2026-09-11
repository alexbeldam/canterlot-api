from beanie import PydanticObjectId
from beanie.operators import Set

from canterlot.models import RatingStats, ReadBookModel
from canterlot.pagination import Page, SortDirection
from canterlot.repositories import ReadBookRepository


class BeanieReadBookRepository(ReadBookRepository):
    async def upsert(self, user_id: PydanticObjectId, book_id: PydanticObjectId, rating: float | None) -> None:
        update_fields: dict[str, object] = {}
        if rating is not None:
            update_fields["rating"] = rating

        await ReadBookModel.find_one(
            ReadBookModel.user_id == user_id,
            ReadBookModel.book_id == book_id,
        ).upsert(
            Set(update_fields),
            on_insert=ReadBookModel(user_id=user_id, book_id=book_id, rating=rating),
        )

    async def find_rating_stats_by_book_id(self, book_id: PydanticObjectId) -> RatingStats:
        results = (
            await ReadBookModel.find(
                ReadBookModel.book_id == book_id,
                ReadBookModel.rating != None,  # noqa: E711
            )
            .aggregate(
                [
                    {
                        "$group": {
                            "_id": None,
                            "average_rating": {"$avg": "$rating"},
                            "rating_count": {"$sum": 1},
                        }
                    }
                ]
            )
            .to_list()
        )

        if not results:
            return RatingStats(average_rating=None, rating_count=0)

        return RatingStats(average_rating=results[0]["average_rating"], rating_count=results[0]["rating_count"])

    async def find_page_by_user_id(
        self,
        user_id: PydanticObjectId,
        page: int,
        limit: int,
        sort_direction: SortDirection = SortDirection.DESC,
    ) -> Page[ReadBookModel]:
        query = ReadBookModel.find(ReadBookModel.user_id == user_id)
        total_items = await query.count()

        sort_field = "-read_at" if sort_direction == SortDirection.DESC else "+read_at"
        items = await query.sort(sort_field).skip((page - 1) * limit).limit(limit).to_list()

        return Page(items=items, total_items=total_items, current_page=page, page_size=limit)
