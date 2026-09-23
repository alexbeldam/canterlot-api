import re

from beanie import PydanticObjectId
from beanie.operators import In, NotIn
from pymongo.errors import DuplicateKeyError

from canterlot.models import BookModel, CatalogEntryModel
from canterlot.pagination import Page, SortDirection
from canterlot.repositories import CatalogRepository

_SORT_FIELD_PATHS = {
    "suggested_at": "suggested_at",
    "title": "book.title",
    "author": "book.authors",
    "year": "book.year",
}
_BOOK_JOINED_SORT_FIELDS = {"title", "author", "year"}


class BeanieCatalogRepository(CatalogRepository):
    async def find_by_club_id_and_book_id(
        self,
        club_id: PydanticObjectId,
        book_id: PydanticObjectId,
    ) -> CatalogEntryModel | None:
        return await CatalogEntryModel.find_one(
            CatalogEntryModel.club_id == club_id,
            CatalogEntryModel.book_id == book_id,
        )

    async def find_page_by_club_id(
        self,
        club_id: PydanticObjectId,
        page: int,
        limit: int,
        sort_by: str | None = None,
        sort_direction: SortDirection = SortDirection.DESC,
        suggested_by: PydanticObjectId | None = None,
        q: str | None = None,
    ) -> Page[CatalogEntryModel]:
        sort_field = sort_by if sort_by in _SORT_FIELD_PATHS else "suggested_at"
        direction = 1 if sort_direction == SortDirection.ASC else -1

        match: dict[str, object] = {"club_id": club_id}
        if suggested_by is not None:
            match["suggested_by"] = suggested_by

        if sort_field in _BOOK_JOINED_SORT_FIELDS or q is not None:
            return await self.__find_book_joined_page(match, _SORT_FIELD_PATHS[sort_field], direction, page, limit, q)

        query = CatalogEntryModel.find(match)
        total_items = await query.count()
        sort_key = "+suggested_at" if sort_direction == SortDirection.ASC else "-suggested_at"
        items = await query.sort(sort_key).skip((page - 1) * limit).limit(limit).to_list()

        return Page(items=items, total_items=total_items, current_page=page, page_size=limit)

    async def __find_book_joined_page(
        self,
        match: dict[str, object],
        sort_path: str,
        direction: int,
        page: int,
        limit: int,
        q: str | None,
    ) -> Page[CatalogEntryModel]:
        pipeline: list[dict] = [
            {"$match": match},
            {
                "$lookup": {
                    "from": BookModel.get_settings().name,
                    "localField": "book_id",
                    "foreignField": "_id",
                    "as": "book",
                }
            },
            {"$unwind": {"path": "$book", "preserveNullAndEmptyArrays": True}},
        ]

        if q is not None:
            pattern = re.escape(q)
            pipeline.append(
                {
                    "$match": {
                        "$or": [
                            {"book.title": {"$regex": pattern, "$options": "i"}},
                            {"book.authors": {"$regex": pattern, "$options": "i"}},
                        ]
                    }
                }
            )

        pipeline.append({"$sort": {sort_path: direction}})
        pipeline.append(
            {
                "$facet": {
                    "items": [
                        {"$skip": (page - 1) * limit},
                        {"$limit": limit},
                        {"$project": {"book": 0}},
                    ],
                    "total": [{"$count": "count"}],
                }
            }
        )

        result = await CatalogEntryModel.aggregate(pipeline).to_list()
        facet = result[0]

        items = [CatalogEntryModel.model_validate(item) for item in facet["items"]]
        total_items = facet["total"][0]["count"] if facet["total"] else 0

        return Page(items=items, total_items=total_items, current_page=page, page_size=limit)

    async def find_by_club_id_excluding_book_ids(
        self,
        club_id: PydanticObjectId,
        excluded_book_ids: set[PydanticObjectId],
    ) -> list[CatalogEntryModel]:
        return await CatalogEntryModel.find(
            CatalogEntryModel.club_id == club_id,
            NotIn(CatalogEntryModel.book_id, list(excluded_book_ids)),
        ).to_list()

    async def find_by_club_id_and_book_ids(
        self,
        club_id: PydanticObjectId,
        book_ids: set[PydanticObjectId],
    ) -> list[CatalogEntryModel]:
        return await CatalogEntryModel.find(
            CatalogEntryModel.club_id == club_id,
            In(CatalogEntryModel.book_id, list(book_ids)),
        ).to_list()

    async def add(self, entry: CatalogEntryModel) -> bool:
        try:
            await entry.insert()
            return True
        except DuplicateKeyError:
            return False

    async def delete_by_club_id_and_book_id(self, club_id: PydanticObjectId, book_id: PydanticObjectId) -> None:
        await CatalogEntryModel.find_one(
            CatalogEntryModel.club_id == club_id,
            CatalogEntryModel.book_id == book_id,
        ).delete()
