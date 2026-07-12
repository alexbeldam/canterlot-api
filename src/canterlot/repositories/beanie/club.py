from datetime import datetime
from typing import cast

from beanie import PydanticObjectId
from beanie.operators import Pull, Push
from pydantic import BaseModel
from pymongo.results import UpdateResult

from canterlot.exceptions import ClubNotFoundError
from canterlot.models import BookModel, ClubModel, MemberRole, MemberSchema, PendingApprovalSchema
from canterlot.models.club import CatalogEntryModel, ClubNameStr, ClubSlugStr
from canterlot.pagination import Page, SortDirection
from canterlot.repositories import ClubRepository
from canterlot.utils.format import LanguageStr

_CATALOG_SORT_FIELD_PATHS = {
    "suggested_at": "catalog.suggested_at",
    "title": "book.title",
    "author": "book.authors",
    "year": "book.year",
}
_BOOK_JOINED_SORT_FIELDS = {"title", "author", "year"}


class MemberProjection(BaseModel):
    members: list[MemberSchema]


class AllowSuggestionProjection(BaseModel):
    allow_suggestions: bool


class PreferredLanguagesProjection(BaseModel):
    preferred_languages: list[LanguageStr]


class NameProjection(BaseModel):
    name: ClubNameStr


class CatalogProjection(BaseModel):
    catalog: list[CatalogEntryModel]


class BeanieClubRepository(ClubRepository):
    async def find_by_id(self, club_id: PydanticObjectId) -> ClubModel | None:
        return await ClubModel.get(club_id)

    async def find_club_name_by_id(self, club_id: PydanticObjectId) -> ClubNameStr | None:
        projection = await ClubModel.find_one(ClubModel.id == club_id).project(NameProjection)

        if not projection:
            return None
        return projection.name

    async def get_preferred_languages_by_id(self, club_id: PydanticObjectId) -> list[LanguageStr]:
        query = ClubModel.find_one(ClubModel.id == club_id)

        projection = await query.project(PreferredLanguagesProjection)

        if not projection:
            raise ClubNotFoundError("This club no longer exists.")

        return projection.preferred_languages

    async def find_member_role_by_club_id_and_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> MemberRole | None:
        query = ClubModel.find_one(ClubModel.id == club_id, ClubModel.members.user_id == user_id)

        projected = await query.project(MemberProjection)

        if not projected or not projected.members:
            return None

        target = next((m for m in projected.members if m.user_id == user_id), None)

        return target.role if target else None

    async def find_by_slug(self, slug: ClubSlugStr) -> ClubModel | None:
        return await ClubModel.find_one(ClubModel.slug == slug)

    async def exists_by_club_slug(self, slug: ClubSlugStr) -> bool:
        count = await ClubModel.find(ClubModel.slug == slug).count()

        return count > 0

    async def exists_by_club_id_and_member_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> bool:
        count = await ClubModel.find(ClubModel.id == club_id, ClubModel.members.user_id == user_id).count()

        return count > 0

    async def exists_by_club_id_and_pending_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> bool:
        count = await ClubModel.find(ClubModel.id == club_id, ClubModel.pending_approvals.user_id == user_id).count()

        return count > 0

    async def exists_by_club_id_and_catalog_book_id(
        self,
        club_id: PydanticObjectId,
        book_id: PydanticObjectId,
    ) -> bool:
        count = await ClubModel.find(ClubModel.id == club_id, ClubModel.catalog.book_id == book_id).count()

        return count > 0

    async def find_catalog_entry_by_club_id_and_book_id(
        self,
        club_id: PydanticObjectId,
        book_id: PydanticObjectId,
    ) -> CatalogEntryModel | None:
        query = ClubModel.find_one(ClubModel.id == club_id, ClubModel.catalog.book_id == book_id)

        projected = await query.project(CatalogProjection)

        if not projected or not projected.catalog:
            return None

        return next((entry for entry in projected.catalog if entry.book_id == book_id), None)

    async def find_catalog_page_by_club_id(
        self,
        club_id: PydanticObjectId,
        page: int,
        limit: int,
        sort_by: str | None = None,
        sort_direction: SortDirection = SortDirection.DESC,
        suggested_by: PydanticObjectId | None = None,
    ) -> Page[CatalogEntryModel]:
        sort_field = sort_by if sort_by in _CATALOG_SORT_FIELD_PATHS else "suggested_at"
        sort_path = _CATALOG_SORT_FIELD_PATHS[sort_field]
        direction = 1 if sort_direction == SortDirection.ASC else -1

        pipeline: list[dict] = [{"$match": {"_id": club_id}}, {"$unwind": "$catalog"}]

        if suggested_by is not None:
            pipeline.append({"$match": {"catalog.suggested_by": suggested_by}})

        if sort_field in _BOOK_JOINED_SORT_FIELDS:
            pipeline.append(
                {
                    "$lookup": {
                        "from": BookModel.get_settings().name,
                        "localField": "catalog.book_id",
                        "foreignField": "_id",
                        "as": "book",
                    }
                }
            )
            pipeline.append({"$unwind": {"path": "$book", "preserveNullAndEmptyArrays": True}})

        pipeline.append({"$sort": {sort_path: direction}})
        pipeline.append(
            {
                "$facet": {
                    "items": [
                        {"$skip": (page - 1) * limit},
                        {"$limit": limit},
                        {"$replaceRoot": {"newRoot": "$catalog"}},
                    ],
                    "total": [{"$count": "count"}],
                }
            }
        )

        result = await ClubModel.aggregate(pipeline).to_list()
        facet = result[0] if result else {"items": [], "total": []}

        items = [CatalogEntryModel(**item) for item in facet["items"]]
        total_items = facet["total"][0]["count"] if facet["total"] else 0

        return Page(items=items, total_items=total_items, current_page=page, page_size=limit)

    async def is_suggestions_allowed(self, club_id: PydanticObjectId) -> bool:
        query = ClubModel.find_one(ClubModel.id == club_id)

        projection = await query.project(AllowSuggestionProjection)

        return projection.allow_suggestions if projection else False

    async def add_member(self, club_id: PydanticObjectId, member: MemberSchema) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Push({ClubModel.members: member}))

    async def add_to_pending_approvals(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        entry = PendingApprovalSchema(user_id=user_id)

        await ClubModel.find_one(ClubModel.id == club_id).update_one(Push({ClubModel.pending_approvals: entry}))

    async def add_to_banned_users(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Push({ClubModel.banned_users: user_id}))

    async def add_to_catalog(self, club_id: PydanticObjectId, entry: CatalogEntryModel) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Push({ClubModel.catalog: entry}))

    async def remove_member(self, club_id: PydanticObjectId, member_id: PydanticObjectId) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Pull({ClubModel.members: {"user_id": member_id}}))

    async def remove_from_pending_approvals(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(
            Pull({ClubModel.pending_approvals: {"user_id": user_id}})
        )

    async def remove_from_banned_users(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Pull({ClubModel.banned_users: user_id}))

    async def remove_from_catalog(self, club_id: PydanticObjectId, book_id: PydanticObjectId) -> None:
        await ClubModel.find_one(ClubModel.id == club_id).update_one(Pull({ClubModel.catalog: {"book_id": book_id}}))

    async def transfer_ownership(
        self,
        club_id: PydanticObjectId,
        current_owner_id: PydanticObjectId,
        new_owner_id: PydanticObjectId,
        transferred_at: datetime,
    ) -> bool:
        # current_owner_id's OWNER role is part of the top-level filter, not just the array
        # filter, so a stale caller races to matched_count == 0 instead of silently no-opping.
        result = await ClubModel.find_one(
            ClubModel.id == club_id,
            {"members": {"$elemMatch": {"user_id": current_owner_id, "role": MemberRole.OWNER}}},
        ).update_one(
            {
                "$set": {
                    "members.$[oldOwner].role": MemberRole.ADMIN,
                    "members.$[newOwner].role": MemberRole.OWNER,
                    "ownership_transferred_at": transferred_at,
                    "protected_former_owner_id": current_owner_id,
                }
            },
            array_filters=[
                {"oldOwner.user_id": current_owner_id},
                {"newOwner.user_id": new_owner_id},
            ],
        )

        return cast(UpdateResult, result).matched_count > 0

    async def reclaim_ownership(
        self,
        club_id: PydanticObjectId,
        former_owner_id: PydanticObjectId,
        current_owner_id: PydanticObjectId,
    ) -> bool:
        result = await ClubModel.find_one(
            ClubModel.id == club_id,
            ClubModel.protected_former_owner_id == former_owner_id,
        ).update_one(
            {
                "$set": {
                    "members.$[formerOwner].role": MemberRole.OWNER,
                    "members.$[currentOwner].role": MemberRole.ADMIN,
                    "ownership_transferred_at": None,
                    "protected_former_owner_id": None,
                }
            },
            array_filters=[
                {"formerOwner.user_id": former_owner_id},
                {"currentOwner.user_id": current_owner_id},
            ],
        )

        return cast(UpdateResult, result).matched_count > 0

    async def save(self, club: ClubModel) -> ClubModel:
        return await club.save()
