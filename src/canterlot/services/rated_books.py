from beanie import PydanticObjectId

from canterlot.dto.book import RatedBook
from canterlot.pagination import Page, SortDirection
from canterlot.repositories import BookRepository, ReadBookRepository


async def resolve_rated_books_page(
    book_repo: BookRepository,
    read_book_repo: ReadBookRepository,
    user_id: PydanticObjectId,
    page: int,
    limit: int,
    sort_direction: SortDirection = SortDirection.DESC,
) -> Page[RatedBook]:
    read_books_page = await read_book_repo.find_page_by_user_id(user_id, page, limit, sort_direction)
    books_by_id = await book_repo.find_by_ids([entry.book_id for entry in read_books_page.items])

    return read_books_page.map(
        lambda entry: RatedBook(book=books_by_id[entry.book_id], rating=entry.rating, read_at=entry.read_at)
    )
