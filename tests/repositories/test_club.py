from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from pymongo.errors import OperationFailure

from canterlot.exceptions import ClubNotFoundError
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.club import CatalogEntryModel, ClubModel, MemberSchema, PendingApprovalSchema
from canterlot.models.enums import BookProviderName, JoinPolicy, MemberRole
from canterlot.pagination import SortDirection
from canterlot.repositories.beanie.club import BeanieClubRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieClubRepository()


def _id(document: BookModel | ClubModel) -> PydanticObjectId:
    return PydanticObjectId(document.id)


async def _book(title: str, year: int, external_id: str) -> BookModel:
    return await BookModel(
        external_id=BookProviderIdentifier(BookProviderName.GOOGLE, external_id),
        title=title,
        year=year,
        created_at=datetime.now(UTC),
    ).insert()


async def _club(**overrides: object) -> ClubModel:
    defaults = {"name": "Book Club", "slug": "book-club"}
    return await ClubModel(**{**defaults, **overrides}).insert()


def describe_find_catalog_page_by_club_id():
    async def it_sorts_by_title_via_a_lookup_join():
        zebra = await _book("Zebra Book", 2020, "zebra")
        alpha = await _book("Alpha Book", 2010, "alpha")
        suggester = PydanticObjectId()
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(zebra), suggested_by=suggester),
                CatalogEntryModel(book_id=_id(alpha), suggested_by=suggester),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(
            _id(club), page=1, limit=10, sort_by="title", sort_direction=SortDirection.ASC
        )

        assert [entry.book_id for entry in page.items] == [_id(alpha), _id(zebra)]
        assert page.total_items == 2

    async def it_sorts_by_year_via_a_lookup_join():
        newer = await _book("Newer Book", 2020, "newer")
        older = await _book("Older Book", 2010, "older")
        suggester = PydanticObjectId()
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(newer), suggested_by=suggester),
                CatalogEntryModel(book_id=_id(older), suggested_by=suggester),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(
            _id(club), page=1, limit=10, sort_by="year", sort_direction=SortDirection.ASC
        )

        assert [entry.book_id for entry in page.items] == [_id(older), _id(newer)]

    async def it_sorts_by_suggested_at_descending_by_default():
        book_a = await _book("Book A", 2020, "a")
        book_b = await _book("Book B", 2020, "b")
        suggester = PydanticObjectId()
        now = datetime.now(UTC)
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(book_a), suggested_by=suggester, suggested_at=now - timedelta(days=1)),
                CatalogEntryModel(book_id=_id(book_b), suggested_by=suggester, suggested_at=now),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10)

        assert [entry.book_id for entry in page.items] == [_id(book_b), _id(book_a)]

    async def it_sorts_ascending_when_requested():
        book_a = await _book("Book A", 2020, "asc-a")
        book_b = await _book("Book B", 2020, "asc-b")
        suggester = PydanticObjectId()
        now = datetime.now(UTC)
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(book_a), suggested_by=suggester, suggested_at=now - timedelta(days=1)),
                CatalogEntryModel(book_id=_id(book_b), suggested_by=suggester, suggested_at=now),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, sort_direction=SortDirection.ASC)

        assert [entry.book_id for entry in page.items] == [_id(book_a), _id(book_b)]

    async def it_paginates_with_skip_and_limit():
        books = [await _book(f"Book {i}", 2020, f"page-{i}") for i in range(3)]
        suggester = PydanticObjectId()
        now = datetime.now(UTC)
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(book), suggested_by=suggester, suggested_at=now + timedelta(seconds=i))
                for i, book in enumerate(books)
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=2, limit=1)

        assert len(page.items) == 1
        assert page.total_items == 3
        assert page.items[0].book_id == _id(books[1])

    async def it_filters_by_suggested_by():
        book_a = await _book("Book A", 2020, "filter-a")
        book_b = await _book("Book B", 2020, "filter-b")
        alice, bob = PydanticObjectId(), PydanticObjectId()
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(book_a), suggested_by=alice),
                CatalogEntryModel(book_id=_id(book_b), suggested_by=bob),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, suggested_by=alice)

        assert page.total_items == 1
        assert page.items[0].book_id == _id(book_a)

    async def it_filters_by_free_text_query_matching_title():
        matching = await _book("The Great Gatsby", 2020, "q-title-match")
        other = await _book("Moby Dick", 1851, "q-title-other")
        suggester = PydanticObjectId()
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(matching), suggested_by=suggester),
                CatalogEntryModel(book_id=_id(other), suggested_by=suggester),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="great gatsby")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_filters_by_free_text_query_matching_authors():
        matching = await BookModel(
            external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "q-author-match"),
            title="Some Book",
            authors=["Jane Austen"],
        ).insert()
        other = await _book("Other Book", 2020, "q-author-other")
        suggester = PydanticObjectId()
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(matching), suggested_by=suggester),
                CatalogEntryModel(book_id=_id(other), suggested_by=suggester),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="austen")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_escapes_regex_special_characters_in_the_query():
        book = await _book("C++ Primer", 2020, "q-regex-escape")
        suggester = PydanticObjectId()
        club = await _club(catalog=[CatalogEntryModel(book_id=_id(book), suggested_by=suggester)])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="C++")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(book)

    async def it_returns_no_matches_when_the_query_matches_nothing():
        book = await _book("Some Book", 2020, "q-no-match")
        suggester = PydanticObjectId()
        club = await _club(catalog=[CatalogEntryModel(book_id=_id(book), suggested_by=suggester)])

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, q="nonexistent phrase")

        assert page.total_items == 0
        assert page.items == []

    async def it_falls_back_to_suggested_at_for_an_unrecognized_sort_field():
        book_a = await _book("Book A", 2020, "fallback-a")
        book_b = await _book("Book B", 2020, "fallback-b")
        suggester = PydanticObjectId()
        now = datetime.now(UTC)
        club = await _club(
            catalog=[
                CatalogEntryModel(book_id=_id(book_a), suggested_by=suggester, suggested_at=now - timedelta(days=1)),
                CatalogEntryModel(book_id=_id(book_b), suggested_by=suggester, suggested_at=now),
            ]
        )

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10, sort_by="not-a-real-field")

        assert [entry.book_id for entry in page.items] == [_id(book_b), _id(book_a)]

    async def it_returns_an_empty_page_for_a_club_with_no_catalog():
        club = await _club()

        page = await repo.find_catalog_page_by_club_id(_id(club), page=1, limit=10)

        assert page.items == []
        assert page.total_items == 0


def describe_find_by_id():
    async def it_finds_a_club_by_id():
        club = await _club()

        found = await repo.find_by_id(_id(club))

        assert found is not None
        assert found.slug == "book-club"

    async def it_returns_none_when_the_club_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_club_name_by_id():
    async def it_returns_the_club_name():
        club = await _club(name="The Canterlot Archives")

        assert await repo.find_club_name_by_id(_id(club)) == "The Canterlot Archives"

    async def it_returns_none_when_the_club_does_not_exist():
        assert await repo.find_club_name_by_id(PydanticObjectId()) is None


def describe_get_preferred_languages_by_id():
    async def it_returns_the_preferred_languages():
        club = await _club(preferred_languages=["en", "pt-BR"])

        assert await repo.get_preferred_languages_by_id(_id(club)) == ["en", "pt-BR"]

    async def it_raises_club_not_found_when_the_club_does_not_exist():
        try:
            await repo.get_preferred_languages_by_id(PydanticObjectId())
            raise AssertionError("expected ClubNotFoundError")
        except ClubNotFoundError:
            pass


def describe_find_member_role_by_club_id_and_user_id():
    async def it_returns_the_members_role():
        member_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=member_id, role=MemberRole.ADMIN)])

        role = await repo.find_member_role_by_club_id_and_user_id(_id(club), member_id)

        assert role == MemberRole.ADMIN

    async def it_returns_none_when_the_user_is_not_a_member():
        club = await _club()

        assert await repo.find_member_role_by_club_id_and_user_id(_id(club), PydanticObjectId()) is None


def describe_find_by_slug():
    async def it_finds_a_club_by_slug():
        await _club(slug="the-canterlot-archives")

        found = await repo.find_by_slug("the-canterlot-archives")

        assert found is not None
        assert found.slug == "the-canterlot-archives"

    async def it_returns_none_when_the_slug_does_not_exist():
        assert await repo.find_by_slug("no-such-slug") is None


def describe_find_id_by_slug():
    async def it_finds_a_clubs_id_by_slug():
        club = await _club(slug="the-canterlot-archives")

        found_id = await repo.find_id_by_slug("the-canterlot-archives")

        assert found_id == _id(club)

    async def it_returns_none_when_the_slug_does_not_exist():
        assert await repo.find_id_by_slug("no-such-slug") is None


def describe_exists_by_club_slug():
    async def it_returns_true_when_the_slug_exists():
        await _club(slug="existing-slug")

        assert await repo.exists_by_club_slug("existing-slug") is True

    async def it_returns_false_when_the_slug_does_not_exist():
        assert await repo.exists_by_club_slug("missing-slug") is False


def describe_exists_by_club_id_and_member_user_id():
    async def it_returns_true_for_an_existing_member():
        member_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=member_id)])

        assert await repo.exists_by_club_id_and_member_user_id(_id(club), member_id) is True

    async def it_returns_false_for_a_non_member():
        club = await _club()

        assert await repo.exists_by_club_id_and_member_user_id(_id(club), PydanticObjectId()) is False


def describe_exists_by_club_id_and_pending_user_id():
    async def it_returns_true_for_a_pending_user():
        pending_id = PydanticObjectId()
        club = await _club(pending_approvals=[PendingApprovalSchema(user_id=pending_id)])

        assert await repo.exists_by_club_id_and_pending_user_id(_id(club), pending_id) is True

    async def it_returns_false_for_a_non_pending_user():
        club = await _club()

        assert await repo.exists_by_club_id_and_pending_user_id(_id(club), PydanticObjectId()) is False


def describe_exists_by_club_id_and_catalog_book_id():
    async def it_returns_true_when_the_book_is_in_the_catalog():
        book = await _book("A Book", 2020, "exists-in-catalog")
        club = await _club(catalog=[CatalogEntryModel(book_id=_id(book), suggested_by=PydanticObjectId())])

        assert await repo.exists_by_club_id_and_catalog_book_id(_id(club), _id(book)) is True

    async def it_returns_false_when_the_book_is_not_in_the_catalog():
        club = await _club()

        assert await repo.exists_by_club_id_and_catalog_book_id(_id(club), PydanticObjectId()) is False


def describe_find_catalog_entry_by_club_id_and_book_id():
    async def it_finds_the_catalog_entry():
        book = await _book("A Book", 2020, "find-entry")
        suggester = PydanticObjectId()
        club = await _club(catalog=[CatalogEntryModel(book_id=_id(book), suggested_by=suggester)])

        entry = await repo.find_catalog_entry_by_club_id_and_book_id(_id(club), _id(book))

        assert entry is not None
        assert entry.suggested_by == suggester

    async def it_returns_none_when_the_book_is_not_in_the_catalog():
        club = await _club()

        assert await repo.find_catalog_entry_by_club_id_and_book_id(_id(club), PydanticObjectId()) is None


def describe_is_suggestions_allowed():
    async def it_returns_true_when_suggestions_are_allowed():
        club = await _club(allow_suggestions=True)

        assert await repo.is_suggestions_allowed(_id(club)) is True

    async def it_returns_false_when_suggestions_are_disallowed():
        club = await _club(allow_suggestions=False)

        assert await repo.is_suggestions_allowed(_id(club)) is False


def describe_add_member():
    async def it_appends_a_member():
        club = await _club()
        member_id = PydanticObjectId()

        await repo.add_member(_id(club), MemberSchema(user_id=member_id, role=MemberRole.ADMIN))

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [m.user_id for m in found.members] == [member_id]


def describe_add_to_pending_approvals():
    async def it_appends_a_pending_approval():
        club = await _club()
        user_id = PydanticObjectId()

        await repo.add_to_pending_approvals(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [p.user_id for p in found.pending_approvals] == [user_id]


def describe_add_to_catalog():
    async def it_appends_a_catalog_entry():
        club = await _club()
        book = await _book("A Book", 2020, "add-to-catalog")
        entry = CatalogEntryModel(book_id=_id(book), suggested_by=PydanticObjectId())

        await repo.add_to_catalog(_id(club), entry)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert [e.book_id for e in found.catalog] == [_id(book)]


def describe_remove_member():
    async def it_removes_a_member():
        member_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=member_id)])

        await repo.remove_member(_id(club), member_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.members == []


def describe_remove_and_ban_member():
    async def it_atomically_removes_the_member_and_bans_them():
        member_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=member_id)])

        await repo.remove_and_ban_member(_id(club), member_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.members == []
        assert found.banned_users == [member_id]


def describe_remove_from_pending_approvals():
    async def it_removes_a_pending_approval():
        user_id = PydanticObjectId()
        club = await _club(pending_approvals=[PendingApprovalSchema(user_id=user_id)])

        await repo.remove_from_pending_approvals(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.pending_approvals == []


def describe_remove_from_banned_users():
    async def it_removes_a_banned_user():
        user_id = PydanticObjectId()
        club = await _club(banned_users=[user_id])

        await repo.remove_from_banned_users(_id(club), user_id)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.banned_users == []


def describe_remove_from_catalog():
    async def it_removes_a_catalog_entry():
        book = await _book("A Book", 2020, "remove-from-catalog")
        club = await _club(catalog=[CatalogEntryModel(book_id=_id(book), suggested_by=PydanticObjectId())])

        await repo.remove_from_catalog(_id(club), _id(book))

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.catalog == []


def describe_transfer_ownership():
    async def it_swaps_roles_and_records_transfer_bookkeeping():
        old_owner_id = PydanticObjectId()
        new_owner_id = PydanticObjectId()
        club = await _club(
            members=[
                MemberSchema(user_id=old_owner_id, role=MemberRole.OWNER),
                MemberSchema(user_id=new_owner_id, role=MemberRole.MEMBER),
            ]
        )
        transferred_at = datetime.now(UTC)

        matched = await repo.transfer_ownership(_id(club), old_owner_id, new_owner_id, transferred_at)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == old_owner_id) == MemberRole.ADMIN
        assert next(m.role for m in found.members if m.user_id == new_owner_id) == MemberRole.OWNER
        assert found.ownership_transferred_at is not None
        assert abs((found.ownership_transferred_at.replace(tzinfo=UTC) - transferred_at).total_seconds()) < 0.001
        assert found.protected_former_owner_id == old_owner_id

    async def it_returns_false_when_the_caller_is_no_longer_the_owner():
        old_owner_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=old_owner_id, role=MemberRole.MEMBER)])

        matched = await repo.transfer_ownership(_id(club), old_owner_id, PydanticObjectId(), datetime.now(UTC))

        assert matched is False
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.ownership_transferred_at is None

    async def it_raises_when_the_target_is_the_same_as_the_current_owner():
        owner_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=owner_id, role=MemberRole.OWNER)])

        with pytest.raises(OperationFailure):
            await repo.transfer_ownership(_id(club), owner_id, owner_id, datetime.now(UTC))


def describe_change_member_role():
    async def it_changes_the_role_and_persists_it():
        target_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=target_id, role=MemberRole.MEMBER)])

        matched = await repo.change_member_role(_id(club), target_id, MemberRole.ADMIN)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == target_id) == MemberRole.ADMIN

    async def it_returns_false_when_the_target_is_the_owner():
        target_id = PydanticObjectId()
        club = await _club(members=[MemberSchema(user_id=target_id, role=MemberRole.OWNER)])

        matched = await repo.change_member_role(_id(club), target_id, MemberRole.MEMBER)

        assert matched is False
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == target_id) == MemberRole.OWNER

    async def it_returns_false_when_the_target_is_no_longer_a_member():
        club = await _club(members=[MemberSchema(user_id=PydanticObjectId(), role=MemberRole.MEMBER)])

        matched = await repo.change_member_role(_id(club), PydanticObjectId(), MemberRole.ADMIN)

        assert matched is False


def describe_update_settings():
    async def it_updates_only_the_provided_fields():
        club = await _club(description="Old description")

        matched = await repo.update_settings(_id(club), description="New description")

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.description == "New description"
        assert found.name == "Book Club"
        assert found.slug == "book-club"

    async def it_updates_every_field_when_all_are_provided():
        club = await _club()

        matched = await repo.update_settings(
            _id(club),
            name="Renamed Club",
            slug="renamed-club",
            description="A fresh description",
            join_policy=JoinPolicy.RESTRICTED,
            allow_suggestions=False,
            preferred_languages=["en", "pt-BR"],
        )

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.name == "Renamed Club"
        assert found.slug == "renamed-club"
        assert found.description == "A fresh description"
        assert found.join_policy == JoinPolicy.RESTRICTED
        assert found.allow_suggestions is False
        assert found.preferred_languages == ["en", "pt-BR"]

    async def it_returns_false_when_the_club_no_longer_exists():
        matched = await repo.update_settings(PydanticObjectId(), description="New description")

        assert matched is False


def describe_reclaim_ownership():
    async def it_reverses_roles_and_clears_transfer_bookkeeping():
        former_owner_id = PydanticObjectId()
        current_owner_id = PydanticObjectId()
        club = await _club(
            members=[
                MemberSchema(user_id=former_owner_id, role=MemberRole.ADMIN),
                MemberSchema(user_id=current_owner_id, role=MemberRole.OWNER),
            ],
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=former_owner_id,
        )

        matched = await repo.reclaim_ownership(_id(club), former_owner_id, current_owner_id)

        assert matched is True
        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert next(m.role for m in found.members if m.user_id == former_owner_id) == MemberRole.OWNER
        assert next(m.role for m in found.members if m.user_id == current_owner_id) == MemberRole.ADMIN
        assert found.ownership_transferred_at is None
        assert found.protected_former_owner_id is None

    async def it_returns_false_when_the_stored_former_owner_no_longer_matches():
        club = await _club(
            members=[MemberSchema(user_id=PydanticObjectId(), role=MemberRole.OWNER)],
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=PydanticObjectId(),
        )

        matched = await repo.reclaim_ownership(_id(club), PydanticObjectId(), PydanticObjectId())

        assert matched is False


def describe_save():
    async def it_persists_changes_to_an_existing_club():
        club = await _club()

        club.description = "An updated description"
        await repo.save(club)

        found = await repo.find_by_id(_id(club))
        assert found is not None
        assert found.description == "An updated description"


def describe_delete():
    async def it_removes_the_club_document_entirely():
        club = await _club(members=[MemberSchema(user_id=PydanticObjectId(), role=MemberRole.OWNER)])

        await repo.delete(_id(club))

        found = await repo.find_by_id(_id(club))
        assert found is None
