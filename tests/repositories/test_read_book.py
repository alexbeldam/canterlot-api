from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from canterlot.models import ReadBookModel
from canterlot.pagination import SortDirection
from canterlot.repositories.beanie.read_book import BeanieReadBookRepository
from tools.factories import BookFactory, ReadBookFactory, UserFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieReadBookRepository()


def _id(document) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_upsert():
    async def it_inserts_a_new_entry_when_none_exists():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()

        await repo.upsert(_id(user), _id(book), rating=4.0)

        rows = await ReadBookModel.find(ReadBookModel.user_id == _id(user)).to_list()
        assert len(rows) == 1
        assert rows[0].book_id == _id(book)
        assert rows[0].rating == 4.0

    async def it_updates_the_rating_in_place_on_a_repeat_call():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book), rating=2.0)

        await repo.upsert(_id(user), _id(book), rating=5.0)

        rows = await ReadBookModel.find(ReadBookModel.user_id == _id(user)).to_list()
        assert len(rows) == 1
        assert rows[0].rating == 5.0

    async def it_never_produces_a_duplicate_row_for_the_same_book():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()

        await repo.upsert(_id(user), _id(book), rating=None)
        await repo.upsert(_id(user), _id(book), rating=3.5)

        rows = await ReadBookModel.find(ReadBookModel.user_id == _id(user)).to_list()
        assert len(rows) == 1

    async def it_leaves_an_existing_rating_untouched_when_omitted():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book), rating=4.5)

        await repo.upsert(_id(user), _id(book), rating=None)

        rows = await ReadBookModel.find(ReadBookModel.user_id == _id(user)).to_list()
        assert rows[0].rating == 4.5

    async def it_creates_an_unrated_entry_when_no_rating_is_given():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()

        await repo.upsert(_id(user), _id(book), rating=None)

        rows = await ReadBookModel.find(ReadBookModel.user_id == _id(user)).to_list()
        assert rows[0].rating is None


def describe_find_rating_stats_by_book_id():
    async def it_returns_none_average_and_zero_count_when_nobody_has_rated_it():
        book = await BookFactory.create_async()

        stats = await repo.find_rating_stats_by_book_id(_id(book))

        assert stats.average_rating is None
        assert stats.rating_count == 0

    async def it_averages_ratings_from_multiple_users():
        book = await BookFactory.create_async()
        for rating in (5.0, 4.0, 3.0):
            await ReadBookFactory.create_async(user_id=PydanticObjectId(), book_id=_id(book), rating=rating)

        stats = await repo.find_rating_stats_by_book_id(_id(book))

        assert stats.average_rating == 4.0
        assert stats.rating_count == 3

    async def it_excludes_entries_with_no_rating():
        book = await BookFactory.create_async()
        await ReadBookFactory.create_async(user_id=PydanticObjectId(), book_id=_id(book), rating=5.0)
        await ReadBookFactory.create_async(user_id=PydanticObjectId(), book_id=_id(book), rating=None)

        stats = await repo.find_rating_stats_by_book_id(_id(book))

        assert stats.average_rating == 5.0
        assert stats.rating_count == 1


def describe_find_page_by_user_id():
    async def it_returns_an_empty_page_when_the_user_has_read_nothing():
        user = await UserFactory.create_async()

        page = await repo.find_page_by_user_id(_id(user), page=1, limit=20)

        assert page.items == []
        assert page.total_items == 0
        assert page.current_page == 1
        assert page.page_size == 20

    async def it_returns_every_row_for_that_user_up_to_the_limit():
        user = await UserFactory.create_async()
        book_a = await BookFactory.create_async()
        book_b = await BookFactory.create_async()
        await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book_a), rating=3.0)
        await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book_b), rating=None)

        page = await repo.find_page_by_user_id(_id(user), page=1, limit=20)

        assert {row.book_id for row in page.items} == {_id(book_a), _id(book_b)}
        assert page.total_items == 2

    async def it_only_returns_rows_for_the_requested_user():
        user = await UserFactory.create_async()
        other_user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book), rating=None)
        await ReadBookFactory.create_async(user_id=_id(other_user), book_id=_id(book), rating=None)

        page = await repo.find_page_by_user_id(_id(user), page=1, limit=20)

        assert len(page.items) == 1
        assert page.items[0].user_id == _id(user)

    async def it_paginates_with_skip_and_limit():
        user = await UserFactory.create_async()
        books = [await BookFactory.create_async() for _ in range(3)]
        entries = [
            await ReadBookFactory.create_async(user_id=_id(user), book_id=_id(book), rating=None) for book in books
        ]
        ordered = sorted(entries, key=lambda entry: entry.read_at, reverse=True)

        page = await repo.find_page_by_user_id(_id(user), page=2, limit=1)

        assert len(page.items) == 1
        assert page.items[0].book_id == ordered[1].book_id
        assert page.total_items == 3
        assert page.current_page == 2
        assert page.page_size == 1

    async def it_sorts_by_read_at_descending_by_default():
        user = await UserFactory.create_async()
        older_book = await BookFactory.create_async()
        newer_book = await BookFactory.create_async()
        await ReadBookFactory.create_async(
            user_id=_id(user),
            book_id=_id(older_book),
            rating=None,
            read_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        await ReadBookFactory.create_async(
            user_id=_id(user),
            book_id=_id(newer_book),
            rating=None,
            read_at=datetime(2025, 6, 1, tzinfo=UTC),
        )

        page = await repo.find_page_by_user_id(_id(user), page=1, limit=20)

        assert [entry.book_id for entry in page.items] == [_id(newer_book), _id(older_book)]

    async def it_sorts_by_read_at_ascending_when_requested():
        user = await UserFactory.create_async()
        older_book = await BookFactory.create_async()
        newer_book = await BookFactory.create_async()
        await ReadBookFactory.create_async(
            user_id=_id(user),
            book_id=_id(older_book),
            rating=None,
            read_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        await ReadBookFactory.create_async(
            user_id=_id(user),
            book_id=_id(newer_book),
            rating=None,
            read_at=datetime(2025, 6, 1, tzinfo=UTC),
        )

        page = await repo.find_page_by_user_id(_id(user), page=1, limit=20, sort_direction=SortDirection.ASC)

        assert [entry.book_id for entry in page.items] == [_id(older_book), _id(newer_book)]
