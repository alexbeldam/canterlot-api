from datetime import datetime
from typing import cast

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.results import UpdateResult

from canterlot.exceptions import ClubNotFoundError
from canterlot.models import CatalogEntryModel, ClubMembershipModel, ClubModel
from canterlot.repositories import ClubRepository
from canterlot.repositories.beanie.transactions import transactional
from canterlot.types import ClubNameStr, ClubSlugStr, JoinPolicy, LanguageStr, MembershipStatus


class AllowSuggestionProjection(BaseModel):
    allow_suggestions: bool


class PreferredLanguagesProjection(BaseModel):
    preferred_languages: list[LanguageStr]


class NameProjection(BaseModel):
    name: ClubNameStr


class IdProjection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PydanticObjectId = Field(alias="_id")


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

    async def find_by_slug(self, slug: ClubSlugStr) -> ClubModel | None:
        return await ClubModel.find_one(ClubModel.slug == slug)

    async def find_id_by_slug(self, slug: ClubSlugStr) -> PydanticObjectId | None:
        projection = await ClubModel.find_one(ClubModel.slug == slug).project(IdProjection)

        if not projection:
            return None
        return projection.id

    async def exists_by_club_slug(self, slug: ClubSlugStr) -> bool:
        return await ClubModel.find(ClubModel.slug == slug).exists()

    async def is_suggestions_allowed(self, club_id: PydanticObjectId) -> bool:
        query = ClubModel.find_one(ClubModel.id == club_id)

        projection = await query.project(AllowSuggestionProjection)

        return projection.allow_suggestions if projection else False

    @transactional
    async def save_new_club_with_owner(
        self,
        session: AsyncClientSession,
        club: ClubModel,
        owner_id: PydanticObjectId,
        joined_at: datetime,
    ) -> ClubModel:
        await club.insert(session=session)
        await ClubMembershipModel(
            club_id=PydanticObjectId(club.id),
            user_id=owner_id,
            status=MembershipStatus.OWNER,
            joined_at=joined_at,
        ).insert(session=session)

        return club

    async def update_settings(
        self,
        club_id: PydanticObjectId,
        name: ClubNameStr | None = None,
        slug: ClubSlugStr | None = None,
        description: str | None = None,
        join_policy: JoinPolicy | None = None,
        allow_suggestions: bool | None = None,
        preferred_languages: list[LanguageStr] | None = None,
    ) -> bool:
        updates: dict[str, object] = {}
        if name is not None:
            updates["name"] = name
        if slug is not None:
            updates["slug"] = slug
        if description is not None:
            updates["description"] = description
        if join_policy is not None:
            updates["join_policy"] = join_policy
        if allow_suggestions is not None:
            updates["allow_suggestions"] = allow_suggestions
        if preferred_languages is not None:
            updates["preferred_languages"] = preferred_languages

        result = await ClubModel.find_one(ClubModel.id == club_id).update_one({"$set": updates})

        return cast(UpdateResult, result).matched_count > 0

    async def save(self, club: ClubModel) -> ClubModel:
        return await club.save()

    @transactional
    async def delete_with_memberships_and_catalog(
        self,
        session: AsyncClientSession,
        club_id: PydanticObjectId,
    ) -> None:
        await ClubModel.find_one(ClubModel.id == club_id, session=session).delete(session=session)
        await ClubMembershipModel.find(
            ClubMembershipModel.club_id == club_id,
            session=session,
        ).delete(session=session)
        await CatalogEntryModel.find(
            CatalogEntryModel.club_id == club_id,
            session=session,
        ).delete(session=session)
