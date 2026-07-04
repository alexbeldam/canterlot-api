from beanie import PydanticObjectId
from beanie.operators import Or, Set

from canterlot.models import BookModel
from canterlot.models.book import UrlList
from canterlot.models.enums import BookProviderName
from canterlot.repositories import BookRepository


class BeanieBookRepository(BookRepository):
    async def find_by_provider_and_provider_book_id(
        self, provider: BookProviderName, provider_book_id: str
    ) -> BookModel | None:
        return await BookModel.find_one(
            BookModel.provider == provider,
            BookModel.provider_book_id == provider_book_id,
        )

    async def find_by_isbn(self, isbn_10: str | None, isbn_13: str | None) -> BookModel | None:
        conditions = []
        if isbn_10:
            conditions.append(BookModel.isbn_10 == isbn_10)
        if isbn_13:
            conditions.append(BookModel.isbn_13 == isbn_13)

        if not conditions:
            return None

        return await BookModel.find_one(Or(*conditions))

    async def find_by_id(self, book_id: PydanticObjectId) -> BookModel | None:
        return await BookModel.get(book_id)

    async def add_to_urls(self, book_id: PydanticObjectId, urls: UrlList) -> None:
        update_fields = {f"urls.{ext.value}": url for ext, url in urls.items()}

        await BookModel.find_one(BookModel.id == book_id).update_one(Set(update_fields))

    async def fill_missing_fields(self, book_id: PydanticObjectId, fields: dict[str, object]) -> None:
        await BookModel.find_one(BookModel.id == book_id).update_one(Set(fields))

    async def save(self, book: BookModel) -> BookModel:
        return await book.save()
