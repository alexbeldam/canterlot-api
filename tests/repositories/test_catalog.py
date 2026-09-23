import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId

from canterlot.models import BookModel, CatalogEntryModel
from canterlot.models.book import BookProviderIdentifier
from canterlot.pagination import SortDirection
from canterlot.repositories.beanie.catalog import BeanieCatalogRepository
from canterlot.types import BookProviderName
from tools.factories import BookFactory, CatalogEntryFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieCatalogRepository()


def _id(document: BookModel | CatalogEntryModel) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_find_page_by_club_id():
    async def it_sorts_by_title_via_a_lookup_join():
        club_id = PydanticObjectId()
        zebra = await BookFactory.create_async()
        alpha = await BookFactory.create_async()
        books_by_title = sorted([zebra, alpha], key=lambda b: b.title)
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(zebra))
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(alpha))

        page = await repo.find_page_by_club_id(
            club_id,
            page=1,
            limit=10,
            sort_by="title",
            sort_direction=SortDirection.ASC,
        )

        assert [entry.book_id for entry in page.items] == [_id(b) for b in books_by_title]
        assert page.total_items == 2

    async def it_sorts_by_year_via_a_lookup_join():
        club_id = PydanticObjectId()
        newer = await BookFactory.create_async(year=2020)
        older = await BookFactory.create_async(year=2010)
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(newer))
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(older))

        page = await repo.find_page_by_club_id(
            club_id,
            page=1,
            limit=10,
            sort_by="year",
            sort_direction=SortDirection.ASC,
        )

        assert [entry.book_id for entry in page.items] == [_id(older), _id(newer)]

    async def it_returns_full_entries_from_a_lookup_join():
        club_id = PydanticObjectId()
        book = await BookFactory.create_async()
        entry = await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(book))

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, sort_by="author")

        assert len(page.items) == 1
        found = page.items[0]
        assert found.id == entry.id
        assert found.club_id == club_id
        assert found.suggested_by == entry.suggested_by

    async def it_sorts_by_suggested_at_descending_by_default():
        club_id = PydanticObjectId()
        now = datetime.now(UTC)
        older = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now - timedelta(days=1))
        newer = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now)

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10)

        assert [entry.book_id for entry in page.items] == [newer.book_id, older.book_id]

    async def it_sorts_ascending_when_requested():
        club_id = PydanticObjectId()
        now = datetime.now(UTC)
        older = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now - timedelta(days=1))
        newer = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now)

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, sort_direction=SortDirection.ASC)

        assert [entry.book_id for entry in page.items] == [older.book_id, newer.book_id]

    async def it_paginates_with_skip_and_limit():
        club_id = PydanticObjectId()
        now = datetime.now(UTC)
        entries = [
            await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now + timedelta(seconds=i))
            for i in range(3)
        ]

        page = await repo.find_page_by_club_id(club_id, page=2, limit=1)

        assert len(page.items) == 1
        assert page.total_items == 3
        assert page.items[0].book_id == entries[1].book_id

    async def it_paginates_a_lookup_join_with_skip_and_limit():
        club_id = PydanticObjectId()
        books = [await BookFactory.create_async(year=2000 + i) for i in range(3)]
        for book in books:
            await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(book))

        page = await repo.find_page_by_club_id(
            club_id,
            page=2,
            limit=1,
            sort_by="year",
            sort_direction=SortDirection.ASC,
        )

        assert page.total_items == 3
        assert [entry.book_id for entry in page.items] == [_id(books[1])]

    async def it_filters_by_suggested_by():
        club_id = PydanticObjectId()
        alice, bob = PydanticObjectId(), PydanticObjectId()
        entry_a = await CatalogEntryFactory.create_async(club_id=club_id, suggested_by=alice)
        await CatalogEntryFactory.create_async(club_id=club_id, suggested_by=bob)

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, suggested_by=alice)

        assert page.total_items == 1
        assert page.items[0].book_id == entry_a.book_id

    async def it_filters_by_suggested_by_alongside_a_query():
        club_id = PydanticObjectId()
        alice, bob = PydanticObjectId(), PydanticObjectId()
        alice_book = await BookFactory.create_async(title="Dune")
        bob_book = await BookFactory.create_async(title="Dune Messiah")
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(alice_book), suggested_by=alice)
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(bob_book), suggested_by=bob)

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, suggested_by=alice, q="dune")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(alice_book)

    async def it_filters_by_free_text_query_matching_title():
        club_id = PydanticObjectId()
        matching = await BookFactory.create_async(title="The Great Gatsby")
        other = await BookFactory.create_async(title="Moby Dick")
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(matching))
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(other))

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, q="great gatsby")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_filters_by_free_text_query_matching_authors():
        club_id = PydanticObjectId()
        matching = await BookFactory.create_async(
            external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "q-author-match"),
            authors=["Jane Austen"],
        )
        other = await BookFactory.create_async(authors=["Other Author"])
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(matching))
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(other))

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, q="austen")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(matching)

    async def it_escapes_regex_special_characters_in_the_query():
        club_id = PydanticObjectId()
        book = await BookFactory.create_async(title="C++ Primer")
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(book))

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, q="C++")

        assert page.total_items == 1
        assert page.items[0].book_id == _id(book)

    async def it_returns_no_matches_when_the_query_matches_nothing():
        club_id = PydanticObjectId()
        book = await BookFactory.create_async()
        await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(book))

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, q="nonexistent phrase")

        assert page.total_items == 0
        assert page.items == []

    async def it_falls_back_to_suggested_at_for_an_unrecognized_sort_field():
        club_id = PydanticObjectId()
        now = datetime.now(UTC)
        older = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now - timedelta(days=1))
        newer = await CatalogEntryFactory.create_async(club_id=club_id, suggested_at=now)

        page = await repo.find_page_by_club_id(club_id, page=1, limit=10, sort_by="not-a-real-field")

        assert [entry.book_id for entry in page.items] == [newer.book_id, older.book_id]

    async def it_returns_an_empty_page_for_a_club_with_no_catalog():
        page = await repo.find_page_by_club_id(PydanticObjectId(), page=1, limit=10)

        assert page.items == []
        assert page.total_items == 0

    async def it_returns_an_empty_page_for_a_lookup_join_on_a_club_with_no_catalog():
        page = await repo.find_page_by_club_id(PydanticObjectId(), page=1, limit=10, q="anything")

        assert page.items == []
        assert page.total_items == 0

    async def it_never_includes_another_clubs_entries():
        club_id, other_club_id = PydanticObjectId(), PydanticObjectId()
        book = await BookFactory.create_async(title="Shared Title")
        own = await CatalogEntryFactory.create_async(club_id=club_id, book_id=_id(book))
        await CatalogEntryFactory.create_async(club_id=other_club_id, book_id=_id(book))
        await CatalogEntryFactory.create_async(club_id=other_club_id)

        plain = await repo.find_page_by_club_id(club_id, page=1, limit=10)
        joined = await repo.find_page_by_club_id(club_id, page=1, limit=10, q="shared")

        assert [entry.id for entry in plain.items] == [own.id]
        assert plain.total_items == 1
        assert [entry.id for entry in joined.items] == [own.id]
        assert joined.total_items == 1


def describe_find_by_club_id_and_book_id():
    async def it_finds_the_catalog_entry():
        entry = await CatalogEntryFactory.create_async()

        found = await repo.find_by_club_id_and_book_id(entry.club_id, entry.book_id)

        assert found is not None
        assert found.suggested_by == entry.suggested_by

    async def it_returns_none_when_the_book_is_not_in_the_catalog():
        entry = await CatalogEntryFactory.create_async()

        assert await repo.find_by_club_id_and_book_id(entry.club_id, PydanticObjectId()) is None

    async def it_returns_none_when_the_book_is_only_in_another_clubs_catalog():
        entry = await CatalogEntryFactory.create_async()

        assert await repo.find_by_club_id_and_book_id(PydanticObjectId(), entry.book_id) is None


def describe_find_by_club_id_excluding_book_ids():
    async def it_returns_every_entry_when_nothing_is_excluded():
        club_id = PydanticObjectId()
        first = await CatalogEntryFactory.create_async(club_id=club_id)
        second = await CatalogEntryFactory.create_async(club_id=club_id)

        entries = await repo.find_by_club_id_excluding_book_ids(club_id, set())

        assert {entry.book_id for entry in entries} == {first.book_id, second.book_id}

    async def it_leaves_out_the_excluded_book_ids():
        club_id = PydanticObjectId()
        kept = await CatalogEntryFactory.create_async(club_id=club_id)
        excluded = await CatalogEntryFactory.create_async(club_id=club_id)

        entries = await repo.find_by_club_id_excluding_book_ids(club_id, {excluded.book_id})

        assert [entry.book_id for entry in entries] == [kept.book_id]

    async def it_is_scoped_to_the_club():
        club_id = PydanticObjectId()
        own = await CatalogEntryFactory.create_async(club_id=club_id)
        await CatalogEntryFactory.create_async()

        entries = await repo.find_by_club_id_excluding_book_ids(club_id, set())

        assert [entry.id for entry in entries] == [own.id]


def describe_find_by_club_id_and_book_ids():
    async def it_returns_only_the_requested_book_ids():
        club_id = PydanticObjectId()
        wanted = await CatalogEntryFactory.create_async(club_id=club_id)
        await CatalogEntryFactory.create_async(club_id=club_id)

        entries = await repo.find_by_club_id_and_book_ids(club_id, {wanted.book_id})

        assert [entry.id for entry in entries] == [wanted.id]

    async def it_is_scoped_to_the_club():
        club_id = PydanticObjectId()
        other = await CatalogEntryFactory.create_async()

        assert await repo.find_by_club_id_and_book_ids(club_id, {other.book_id}) == []


def describe_add():
    async def it_inserts_the_entry_and_returns_true():
        entry = CatalogEntryFactory.build(id=None)

        assert await repo.add(entry) is True

        found = await repo.find_by_club_id_and_book_id(entry.club_id, entry.book_id)
        assert found is not None
        assert found.suggested_by == entry.suggested_by

    async def it_returns_false_when_the_book_is_already_in_the_clubs_catalog():
        existing = await CatalogEntryFactory.create_async()
        duplicate = CatalogEntryFactory.build(id=None, club_id=existing.club_id, book_id=existing.book_id)

        assert await repo.add(duplicate) is False

        rows = await CatalogEntryModel.find(CatalogEntryModel.club_id == existing.club_id).to_list()
        assert [row.id for row in rows] == [existing.id]

    async def it_allows_the_same_book_in_two_different_clubs():
        existing = await CatalogEntryFactory.create_async()
        other_club_entry = CatalogEntryFactory.build(id=None, book_id=existing.book_id)

        assert await repo.add(other_club_entry) is True

    async def it_keeps_exactly_one_entry_when_the_same_book_is_suggested_concurrently():
        club_id, book_id = PydanticObjectId(), PydanticObjectId()
        first = CatalogEntryFactory.build(id=None, club_id=club_id, book_id=book_id)
        second = CatalogEntryFactory.build(id=None, club_id=club_id, book_id=book_id)

        results = await asyncio.gather(repo.add(first), repo.add(second))

        assert sorted(results) == [False, True]
        assert await CatalogEntryModel.find(CatalogEntryModel.club_id == club_id).count() == 1


def describe_delete_by_club_id_and_book_id():
    async def it_removes_only_the_target_entry():
        club_id = PydanticObjectId()
        target = await CatalogEntryFactory.create_async(club_id=club_id)
        kept = await CatalogEntryFactory.create_async(club_id=club_id)
        same_book_elsewhere = await CatalogEntryFactory.create_async(book_id=target.book_id)

        await repo.delete_by_club_id_and_book_id(club_id, target.book_id)

        remaining = await CatalogEntryModel.find_all().to_list()
        assert {row.id for row in remaining} == {kept.id, same_book_elsewhere.id}
