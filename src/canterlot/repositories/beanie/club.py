from beanie import PydanticObjectId
from beanie.operators import Pull, Push
from pydantic import BaseModel

from canterlot.exceptions import ClubNotFoundError
from canterlot.models import ClubModel, MemberSchema, PendingApprovalSchema, UserRole
from canterlot.models.club import CatalogEntryModel, ClubSlugStr
from canterlot.repositories import ClubRepository
from canterlot.utils.format import LanguageStr


class MemberProjection(BaseModel):
    members: list[MemberSchema]


class AllowSuggestionProjection(BaseModel):
    allow_suggestions: bool


class PreferredLanguagesProjection(BaseModel):
    preferred_languages: list[LanguageStr]


class BeanieClubRepository(ClubRepository):
    async def find_by_id(self, club_id: PydanticObjectId) -> ClubModel | None:
        return await ClubModel.get(club_id)

    async def get_preferred_languages_by_id(self, club_id: PydanticObjectId) -> list[LanguageStr]:
        query = ClubModel.find_one(ClubModel.id == club_id)

        projection = await query.project(PreferredLanguagesProjection)

        if not projection:
            raise ClubNotFoundError(f"Club with ID '{club_id}' not found")

        return projection.preferred_languages

    async def find_member_role_by_club_id_and_user_id(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
    ) -> UserRole | None:
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

    async def exists_by_club_id_and_catalog_book_id(
        self,
        club_id: PydanticObjectId,
        book_id: PydanticObjectId,
    ) -> bool:
        count = await ClubModel.find(ClubModel.id == club_id, ClubModel.catalog.book_id == book_id).count()

        return count > 0

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

    async def save(self, club: ClubModel) -> ClubModel:
        return await club.save()
