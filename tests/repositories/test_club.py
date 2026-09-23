from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import ClubNotFoundError
from canterlot.models import CatalogEntryModel, ClubMembershipModel
from canterlot.models.club import ClubModel
from canterlot.repositories.beanie.club import BeanieClubRepository
from canterlot.types import JoinPolicy, MembershipStatus
from tools.factories import CatalogEntryFactory, ClubFactory, ClubMembershipFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieClubRepository()


def _id(document: ClubModel) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_find_by_id():
    async def it_finds_a_club_by_id():
        club = await ClubFactory.create_async()

        found = await repo.find_by_id(_id(club))

        assert found is not None
        assert found.slug == club.slug

    async def it_returns_none_when_the_club_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_club_name_by_id():
    async def it_returns_the_club_name():
        club = await ClubFactory.create_async()

        assert await repo.find_club_name_by_id(_id(club)) == club.name

    async def it_returns_none_when_the_club_does_not_exist():
        assert await repo.find_club_name_by_id(PydanticObjectId()) is None


def describe_get_preferred_languages_by_id():
    async def it_returns_the_preferred_languages():
        club = await ClubFactory.create_async()

        assert await repo.get_preferred_languages_by_id(_id(club)) == club.preferred_languages

    async def it_raises_club_not_found_when_the_club_does_not_exist():
        with pytest.raises(ClubNotFoundError):
            await repo.get_preferred_languages_by_id(PydanticObjectId())


def describe_find_by_slug():
    async def it_finds_a_club_by_slug():
        club = await ClubFactory.create_async()

        found = await repo.find_by_slug(club.slug)

        assert found is not None
        assert found.slug == club.slug

    async def it_returns_none_when_the_slug_does_not_exist():
        assert await repo.find_by_slug("no-such-slug") is None


def describe_find_id_by_slug():
    async def it_finds_a_clubs_id_by_slug():
        club = await ClubFactory.create_async()

        found_id = await repo.find_id_by_slug(club.slug)

        assert found_id == _id(club)

    async def it_returns_none_when_the_slug_does_not_exist():
        assert await repo.find_id_by_slug("no-such-slug") is None


def describe_exists_by_club_slug():
    async def it_returns_true_when_the_slug_exists():
        club = await ClubFactory.create_async()

        assert await repo.exists_by_club_slug(club.slug) is True

    async def it_returns_false_when_the_slug_does_not_exist():
        assert await repo.exists_by_club_slug("missing-slug") is False


def describe_is_suggestions_allowed():
    async def it_returns_true_when_suggestions_are_allowed():
        club = await ClubFactory.create_async(allow_suggestions=True)

        assert await repo.is_suggestions_allowed(_id(club)) is True

    async def it_returns_false_when_suggestions_are_disallowed():
        club = await ClubFactory.create_async(allow_suggestions=False)

        assert await repo.is_suggestions_allowed(_id(club)) is False


def describe_save_new_club_with_owner():
    async def it_persists_the_club_and_the_owner_membership_row_together():
        club = ClubModel(name="Test Club", slug="test-club-owner-insert", join_policy=JoinPolicy.PUBLIC)
        owner_id = PydanticObjectId()
        joined_at = datetime.now(UTC)

        saved = await repo.save_new_club_with_owner(club, owner_id, joined_at)

        found = await repo.find_by_id(_id(saved))
        assert found is not None

        membership = await ClubMembershipModel.find_one(
            ClubMembershipModel.club_id == _id(saved),
            ClubMembershipModel.user_id == owner_id,
        )
        assert membership is not None
        assert membership.status == MembershipStatus.OWNER


def describe_update_settings():
    async def it_updates_only_the_provided_fields():
        club = await ClubFactory.create_async()
        new_description = f"Updated: {club.description}"

        matched = await repo.update_settings(_id(club), description=new_description)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.description == new_description
        assert found.name == club.name
        assert found.slug == club.slug

    async def it_updates_every_field_when_all_are_provided():
        club = await ClubFactory.create_async()
        new_name = "Renamed Club"
        new_slug = "renamed-club"
        new_description = "A fresh description"
        new_join_policy = JoinPolicy.RESTRICTED
        new_allow_suggestions = not club.allow_suggestions
        new_preferred_languages = ["en", "pt-BR"]

        matched = await repo.update_settings(
            _id(club),
            name=new_name,
            slug=new_slug,
            description=new_description,
            join_policy=new_join_policy,
            allow_suggestions=new_allow_suggestions,
            preferred_languages=new_preferred_languages,
        )

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.name == new_name
        assert found.slug == new_slug
        assert found.description == new_description
        assert found.join_policy == new_join_policy
        assert found.allow_suggestions == new_allow_suggestions
        assert found.preferred_languages == new_preferred_languages

    async def it_returns_false_when_the_club_no_longer_exists():
        matched = await repo.update_settings(PydanticObjectId(), description="New description")

        assert matched is False


def describe_save():
    async def it_persists_changes_to_an_existing_club():
        club = await ClubFactory.create_async()

        club.description = f"Updated {club.description}"
        await repo.save(club)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.description == club.description


def describe_delete_with_memberships_and_catalog():
    async def it_removes_the_club_document_and_all_its_membership_rows():
        club = await ClubFactory.create_async()
        club_id = _id(club)
        await ClubMembershipFactory.create_async(club_id=club_id, status=MembershipStatus.OWNER)
        await ClubMembershipFactory.create_async(club_id=club_id, status=MembershipStatus.MEMBER)

        await repo.delete_with_memberships_and_catalog(club_id)

        assert await repo.find_by_id(club_id) is None
        remaining = await ClubMembershipModel.find(ClubMembershipModel.club_id == club_id).to_list()
        assert remaining == []

    async def it_removes_every_catalog_entry_for_the_club():
        club = await ClubFactory.create_async()
        club_id = _id(club)
        await CatalogEntryFactory.create_async(club_id=club_id)
        await CatalogEntryFactory.create_async(club_id=club_id)

        await repo.delete_with_memberships_and_catalog(club_id)

        assert await CatalogEntryModel.find(CatalogEntryModel.club_id == club_id).count() == 0

    async def it_leaves_other_clubs_catalog_entries_untouched():
        club = await ClubFactory.create_async()
        other_entry = await CatalogEntryFactory.create_async()

        await repo.delete_with_memberships_and_catalog(_id(club))

        assert await CatalogEntryModel.get(PydanticObjectId(other_entry.id)) is not None
