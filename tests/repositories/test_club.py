from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from pymongo.errors import OperationFailure

from canterlot.exceptions import ClubNotFoundError
from canterlot.factories import BookFactory, CatalogEntryFactory, ClubFactory, MemberFactory
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.club import ClubModel, PendingApprovalSchema
from canterlot.pagination import SortDirection
from canterlot.repositories.beanie.club import BeanieClubRepository
from canterlot.types import BookProviderName, JoinPolicy, MemberRole

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieClubRepository()


def _id(document: BookModel | ClubModel) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_find_catalog_page_by_club_id():
    async def it_sorts_by_title_via_a_lookup_join():
        zebra = await BookFactory.create_async()
        alpha = await BookFactory.create_async()
        books_by_title = sorted([zebra, alpha], key=lambda b: b.title)

        club = await ClubFactory.create_async(
            catalog=[
                CatalogEntryFactory.build(book_id=_id(zebra)),
                CatalogEntryFactory.build(book_id=_id(alpha)),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(
            _id(club),
            page=1,
            limit=10,
            sort_by="title",
            sort_direction=SortDirection.ASC,
        )

        assert [entry.book_id for entry in page.items] == [_id(b) for b in books_by_title]
        assert page.total_items == 2

    async def it_sorts_by_year_via_a_lookup_join():
        newer = await BookFactory.create_async(year=2020)
        older = await BookFactory.create_async(year=2010)
        club = await ClubFactory.create_async(
            catalog=[
                CatalogEntryFactory.build(book_id=_id(newer)),
                CatalogEntryFactory.build(book_id=_id(older)),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(
            _id(club),
            page=1,
            limit=10,
            sort_by="year",
            sort_direction=SortDirection.ASC,
        )

        assert [entry.book_id for entry in page.items] == [_id(older), _id(newer)]

    async def it_sorts_by_suggested_at_descending_by_default():
        now = datetime.now(UTC)
        older = CatalogEntryFactory.build(suggested_at=now - timedelta(days=1))
        newer = CatalogEntryFactory.build(suggested_at=now)

        club = await ClubFactory.create_async(catalog=[older, newer])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10)

        assert [entry.book_id for entry in page.items] == [newer.book_id, older.book_id]

    async def it_sorts_ascending_when_requested():
        now = datetime.now(UTC)
        older = CatalogEntryFactory.build(suggested_at=now - timedelta(days=1))
        newer = CatalogEntryFactory.build(suggested_at=now)

        club = await ClubFactory.create_async(catalog=[older, newer])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, sort_direction=SortDirection.ASC)

        assert [entry.book_id for entry in page.items] == [older.book_id, newer.book_id]

    async def it_paginates_with_skip_and_limit():
        now = datetime.now(UTC)
        entries = [CatalogEntryFactory.build(suggested_at=now + timedelta(seconds=i)) for i in range(3)]
        club = await ClubFactory.create_async(catalog=entries)

        page = await repo.find_catalog_page_by_club_id(_id(club), page=2, limit=1)

        assert len(page.items) == 1
        assert page.total_items == 3
        assert page.items[0].book_id == entries[1].book_id

    async def it_filters_by_suggested_by():
        alice, bob = PydanticObjectId(), PydanticObjectId()
        entry_a = CatalogEntryFactory.build(suggested_by=alice)
        entry_b = CatalogEntryFactory.build(suggested_by=bob)

        club = await ClubFactory.create_async(catalog=[entry_a, entry_b])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, suggested_by=alice)

        assert page.total_items == 1
        assert page.items[0].book_id == entry_a.book_id

    async def it_filters_by_free_text_query_matching_title():
        matching = await BookFactory.create_async(title="The Great Gatsby")
        other = await BookFactory.create_async(title="Moby Dick")
        club = await ClubFactory.create_async(
            catalog=[
                CatalogEntryFactory.build(book_id=_id(matching)),
                CatalogEntryFactory.build(book_id=_id(other)),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="great gatsby")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_filters_by_free_text_query_matching_authors():
        matching = await BookFactory.create_async(
            external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "q-author-match"),
            authors=["Jane Austen"],
        )
        other = await BookFactory.create_async(authors=["Other Author"])
        club = await ClubFactory.create_async(
            catalog=[
                CatalogEntryFactory.build(book_id=_id(matching)),
                CatalogEntryFactory.build(book_id=_id(other)),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="austen")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_escapes_regex_special_characters_in_the_query():
        book = await BookFactory.create_async(title="C++ Primer")
        club = await ClubFactory.create_async(catalog=[CatalogEntryFactory.build(book_id=_id(book))])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="C++")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(book)

    async def it_returns_no_matches_when_the_query_matches_nothing():
        book = await BookFactory.create_async()
        club = await ClubFactory.create_async(catalog=[CatalogEntryFactory.build(book_id=_id(book))])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="nonexistent phrase")

        assert page.total_items == 0
        assert page.items == []

    async def it_falls_back_to_suggested_at_for_an_unrecognized_sort_field():
        now = datetime.now(UTC)
        older = CatalogEntryFactory.build(suggested_at=now - timedelta(days=1))
        newer = CatalogEntryFactory.build(suggested_at=now)

        club = await ClubFactory.create_async(catalog=[older, newer])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, sort_by="not-a-real-field")

        assert [entry.book_id for entry in page.items] == [newer.book_id, older.book_id]

    async def it_returns_an_empty_page_for_a_club_with_no_catalog():
        club = await ClubFactory.create_async()

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10)

        assert page.items == []
        assert page.total_items == 0


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


def describe_find_member_role_by_club_id_and_user_id():
    async def it_returns_the_members_role():
        member = MemberFactory.build(role=MemberRole.ADMIN)
        club = await ClubFactory.create_async(members=[member])

        role = await repo.find_member_role_by_club_id_and_user_id(_id(club), member.user_id)

        assert role == MemberRole.ADMIN

    async def it_returns_none_when_the_user_is_not_a_member():
        club = await ClubFactory.create_async()

        assert await repo.find_member_role_by_club_id_and_user_id(_id(club), PydanticObjectId()) is None


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


def describe_exists_by_club_id_and_member_user_id():
    async def it_returns_true_for_an_existing_member():
        member = MemberFactory.build()
        club = await ClubFactory.create_async(members=[member])

        assert await repo.exists_by_club_id_and_member_user_id(_id(club), member.user_id) is True

    async def it_returns_false_for_a_non_member():
        club = await ClubFactory.create_async()

        assert await repo.exists_by_club_id_and_member_user_id(_id(club), PydanticObjectId()) is False


def describe_exists_by_club_id_and_pending_user_id():
    async def it_returns_true_for_a_pending_user():
        pending_id = PydanticObjectId()
        club = await ClubFactory.create_async(pending_approvals=[PendingApprovalSchema(user_id=pending_id)])

        assert await repo.exists_by_club_id_and_pending_user_id(_id(club), pending_id) is True

    async def it_returns_false_for_a_non_pending_user():
        club = await ClubFactory.create_async()

        assert await repo.exists_by_club_id_and_pending_user_id(_id(club), PydanticObjectId()) is False


def describe_exists_by_club_id_and_catalog_book_id():
    async def it_returns_true_when_the_book_is_in_the_catalog():
        entry = CatalogEntryFactory.build()
        club = await ClubFactory.create_async(catalog=[entry])

        assert await repo.exists_by_club_id_and_catalog_book_id(_id(club), entry.book_id) is True

    async def it_returns_false_when_the_book_is_not_in_the_catalog():
        club = await ClubFactory.create_async()

        assert await repo.exists_by_club_id_and_catalog_book_id(_id(club), PydanticObjectId()) is False


def describe_find_catalog_entry_by_club_id_and_book_id():
    async def it_finds_the_catalog_entry():
        entry = CatalogEntryFactory.build()
        club = await ClubFactory.create_async(catalog=[entry])

        found_entry = await repo.find_catalog_entry_by_club_id_and_book_id(_id(club), entry.book_id)

        assert found_entry is not None
        assert found_entry.suggested_by == entry.suggested_by

    async def it_returns_none_when_the_book_is_not_in_the_catalog():
        club = await ClubFactory.create_async()

        assert await repo.find_catalog_entry_by_club_id_and_book_id(_id(club), PydanticObjectId()) is None


def describe_is_suggestions_allowed():
    async def it_returns_true_when_suggestions_are_allowed():
        club = await ClubFactory.create_async(allow_suggestions=True)

        assert await repo.is_suggestions_allowed(_id(club)) is True

    async def it_returns_false_when_suggestions_are_disallowed():
        club = await ClubFactory.create_async(allow_suggestions=False)

        assert await repo.is_suggestions_allowed(_id(club)) is False


def describe_add_member():
    async def it_appends_a_member():
        club = await ClubFactory.create_async(members=[])
        member = MemberFactory.build(role=MemberRole.ADMIN)

        await repo.add_member(_id(club), member)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [m.user_id for m in found.members] == [member.user_id]


def describe_add_to_pending_approvals():
    async def it_appends_a_pending_approval():
        club = await ClubFactory.create_async(pending_approvals=[])
        user_id = PydanticObjectId()

        await repo.add_to_pending_approvals(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [p.user_id for p in found.pending_approvals] == [user_id]


def describe_add_to_catalog():
    async def it_appends_a_catalog_entry():
        club = await ClubFactory.create_async(catalog=[])
        entry = CatalogEntryFactory.build()

        await repo.add_to_catalog(_id(club), entry)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [e.book_id for e in found.catalog] == [entry.book_id]


def describe_remove_member():
    async def it_removes_a_member():
        member = MemberFactory.build()
        club = await ClubFactory.create_async(members=[member])

        await repo.remove_member(_id(club), member.user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.members == []


def describe_remove_and_ban_member():
    async def it_atomically_removes_the_member_and_bans_them():
        member = MemberFactory.build()
        club = await ClubFactory.create_async(members=[member])

        await repo.remove_and_ban_member(_id(club), member.user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.members == []
        assert found.banned_users == [member.user_id]


def describe_remove_from_pending_approvals():
    async def it_removes_a_pending_approval():
        user_id = PydanticObjectId()
        club = await ClubFactory.create_async(pending_approvals=[PendingApprovalSchema(user_id=user_id)])

        await repo.remove_from_pending_approvals(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.pending_approvals == []


def describe_remove_from_banned_users():
    async def it_removes_a_banned_user():
        user_id = PydanticObjectId()
        club = await ClubFactory.create_async(banned_users=[user_id])

        await repo.remove_from_banned_users(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.banned_users == []


def describe_remove_from_catalog():
    async def it_removes_a_catalog_entry():
        entry = CatalogEntryFactory.build()
        club = await ClubFactory.create_async(catalog=[entry])

        await repo.remove_from_catalog(_id(club), entry.book_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.catalog == []


def describe_transfer_ownership():
    async def it_swaps_roles_and_records_transfer_bookkeeping():
        old_owner = MemberFactory.build(role=MemberRole.OWNER)
        new_owner = MemberFactory.build(role=MemberRole.MEMBER)
        club = await ClubFactory.create_async(members=[old_owner, new_owner])
        transferred_at = datetime.now(UTC)

        matched = await repo.transfer_ownership(_id(club), old_owner.user_id, new_owner.user_id, transferred_at)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == old_owner.user_id) == MemberRole.ADMIN
        assert next(m.role for m in found.members if m.user_id == new_owner.user_id) == MemberRole.OWNER
        assert found.ownership_transferred_at is not None
        assert abs((found.ownership_transferred_at.replace(tzinfo=UTC) - transferred_at).total_seconds()) < 0.001
        assert found.protected_former_owner_id == old_owner.user_id

    async def it_returns_false_when_the_caller_is_no_longer_the_owner():
        non_owner = MemberFactory.build(role=MemberRole.MEMBER)
        club = await ClubFactory.create_async(members=[non_owner])

        matched = await repo.transfer_ownership(_id(club), non_owner.user_id, PydanticObjectId(), datetime.now(UTC))

        assert matched is False
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.ownership_transferred_at is None

    async def it_raises_when_the_target_is_the_same_as_the_current_owner():
        owner = MemberFactory.build(role=MemberRole.OWNER)
        club = await ClubFactory.create_async(members=[owner])

        with pytest.raises(OperationFailure):
            await repo.transfer_ownership(_id(club), owner.user_id, owner.user_id, datetime.now(UTC))


def describe_change_member_role():
    async def it_changes_the_role_and_persists_it():
        target_member = MemberFactory.build(role=MemberRole.MEMBER)
        club = await ClubFactory.create_async(members=[target_member])

        matched = await repo.change_member_role(_id(club), target_member.user_id, MemberRole.ADMIN)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == target_member.user_id) == MemberRole.ADMIN

    async def it_returns_false_when_the_target_is_the_owner():
        owner_member = MemberFactory.build(role=MemberRole.OWNER)
        club = await ClubFactory.create_async(members=[owner_member])

        matched = await repo.change_member_role(_id(club), owner_member.user_id, MemberRole.MEMBER)

        assert matched is False
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == owner_member.user_id) == MemberRole.OWNER

    async def it_returns_false_when_the_target_is_no_longer_a_member():
        club = await ClubFactory.create_async(members=[MemberFactory.build(role=MemberRole.MEMBER)])

        matched = await repo.change_member_role(_id(club), PydanticObjectId(), MemberRole.ADMIN)

        assert matched is False


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


def describe_reclaim_ownership():
    async def it_reverses_roles_and_clears_transfer_bookkeeping():
        former_owner = MemberFactory.build(role=MemberRole.ADMIN)
        current_owner = MemberFactory.build(role=MemberRole.OWNER)
        club = await ClubFactory.create_async(
            members=[former_owner, current_owner],
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=former_owner.user_id,
        )

        matched = await repo.reclaim_ownership(_id(club), former_owner.user_id, current_owner.user_id)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == former_owner.user_id) == MemberRole.OWNER
        assert next(m.role for m in found.members if m.user_id == current_owner.user_id) == MemberRole.ADMIN
        assert found.ownership_transferred_at is None
        assert found.protected_former_owner_id is None

    async def it_returns_false_when_the_stored_former_owner_no_longer_matches():
        club = await ClubFactory.create_async(
            members=[MemberFactory.build(role=MemberRole.OWNER)],
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=PydanticObjectId(),
        )

        matched = await repo.reclaim_ownership(_id(club), PydanticObjectId(), PydanticObjectId())

        assert matched is False


def describe_save():
    async def it_persists_changes_to_an_existing_club():
        club = await ClubFactory.create_async()

        club.description = f"Updated {club.description}"
        await repo.save(club)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.description == club.description


def describe_delete():
    async def it_removes_the_club_document_entirely():
        club = await ClubFactory.create_async(members=[MemberFactory.build(role=MemberRole.OWNER)])

        await repo.delete(_id(club))

        found = await repo.find_by_id(_id(club))
        assert found is None
