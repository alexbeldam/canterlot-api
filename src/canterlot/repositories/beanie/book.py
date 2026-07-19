from beanie import PydanticObjectId
from beanie.operators import In, Or, Set
from pydantic import BaseModel, ConfigDict, Field

from canterlot.models import BookModel
from canterlot.models.book import BookProviderIdentifier, UrlList
from canterlot.repositories import BookRepository
from canterlot.types import ISBNStr


class IdProjection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PydanticObjectId = Field(alias="_id")


class BeanieBookRepository(BookRepository):
    async def find_by_external_id(self, external_id: BookProviderIdentifier) -> BookModel | None:
        return await BookModel.find_one(BookModel.external_id == external_id)

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

    async def find_by_ids(self, book_ids: list[PydanticObjectId]) -> dict[PydanticObjectId, BookModel]:
        if not book_ids:
            return {}

        books = await BookModel.find(In(BookModel.id, book_ids)).to_list()

        return {PydanticObjectId(book.id): book for book in books}

    async def find_id_by_identifier(self, identifier: BookProviderIdentifier | ISBNStr) -> PydanticObjectId | None:
        conditions = []
        if isinstance(identifier, BookProviderIdentifier):
            conditions.append(BookModel.external_id == identifier)
        else:
            conditions.append(BookModel.isbn_10 == identifier)
            conditions.append(BookModel.isbn_13 == identifier)

        projection = await BookModel.find_one(Or(*conditions)).project(IdProjection)

        if not projection:
            return None
        return projection.id

    async def add_to_urls(self, book_id: PydanticObjectId, urls: UrlList) -> None:
        update_fields = {f"urls.{ext.value}": url for ext, url in urls.items()}

        await BookModel.find_one(BookModel.id == book_id).update_one(Set(update_fields))

    async def fill_missing_fields(self, book_id: PydanticObjectId, fields: dict[str, object]) -> None:
        await BookModel.find_one(BookModel.id == book_id).update_one(Set(fields))

    async def save(self, book: BookModel) -> BookModel:
        return await book.save()
