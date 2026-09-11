from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId

from canterlot.pagination import Page, SortDirection
from canterlot.services.rated_books import resolve_rated_books_page
from tools.factories import BookFactory, ReadBookFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_resolve_rated_books_page():
    async def it_returns_an_empty_page_when_the_user_has_read_nothing(book_repo: AsyncMock, read_book_repo: AsyncMock):
        read_book_repo.find_page_by_user_id.return_value = Page(items=[], total_items=0, current_page=1, page_size=20)

        result = await resolve_rated_books_page(book_repo, read_book_repo, SOME_USER_ID, page=1, limit=20)

        assert result.items == []
        assert result.total_items == 0
        book_repo.find_by_ids.assert_awaited_once_with([])

    async def it_pairs_each_read_book_with_its_resolved_book_rating_and_read_at(
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
    ):
        book = BookFactory.build(id=PydanticObjectId())
        read_at = datetime(2025, 6, 1, tzinfo=UTC)
        entry = ReadBookFactory.build(user_id=SOME_USER_ID, book_id=book.id, rating=4.5, read_at=read_at)
        read_book_repo.find_page_by_user_id.return_value = Page(
            items=[entry],
            total_items=1,
            current_page=1,
            page_size=20,
        )
        book_repo.find_by_ids.return_value = {book.id: book}

        result = await resolve_rated_books_page(book_repo, read_book_repo, SOME_USER_ID, page=1, limit=20)

        assert len(result.items) == 1
        assert result.items[0].book == book
        assert result.items[0].rating == 4.5
        assert result.items[0].read_at == read_at
        assert result.total_items == 1

    async def it_forwards_pagination_and_sort_arguments_to_the_repository(
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
    ):
        read_book_repo.find_page_by_user_id.return_value = Page(items=[], total_items=0, current_page=2, page_size=5)

        await resolve_rated_books_page(
            book_repo,
            read_book_repo,
            SOME_USER_ID,
            page=2,
            limit=5,
            sort_direction=SortDirection.ASC,
        )

        read_book_repo.find_page_by_user_id.assert_awaited_once_with(SOME_USER_ID, 2, 5, SortDirection.ASC)
