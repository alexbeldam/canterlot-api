from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId
from pydantic import TypeAdapter

from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.enums import BookProviderName, ExtensionType
from canterlot.repositories.beanie.book import BeanieBookRepository
from canterlot.utils.format import HttpsUrl

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieBookRepository()
_https_url: Callable[[str], HttpsUrl] = TypeAdapter(HttpsUrl).validate_python


def _id(book: BookModel) -> PydanticObjectId:
    return PydanticObjectId(book.id)


async def _book(**overrides: object) -> BookModel:
    defaults = {
        "external_id": BookProviderIdentifier(BookProviderName.GOOGLE, "default-id"),
        "title": "A Book",
        "created_at": datetime.now(UTC),
    }
    return await BookModel(**{**defaults, **overrides}).insert()


def describe_find_by_external_id():
    async def it_finds_a_book_by_external_id():
        external_id = BookProviderIdentifier(BookProviderName.GOOGLE, "find-external")
        await _book(external_id=external_id, title="Found Book")

        found = await repo.find_by_external_id(external_id)

        assert found is not None
        assert found.title == "Found Book"

    async def it_returns_none_when_no_book_matches():
        missing = BookProviderIdentifier(BookProviderName.GOOGLE, "does-not-exist")

        assert await repo.find_by_external_id(missing) is None


def describe_find_by_isbn():
    async def it_finds_a_book_by_isbn_10():
        external_id = BookProviderIdentifier(BookProviderName.GOOGLE, "isbn10-book")
        await _book(external_id=external_id, isbn_10="0306406152")

        found = await repo.find_by_isbn(isbn_10="0306406152", isbn_13=None)

        assert found is not None
        assert found.isbn_10 == "0306406152"

    async def it_finds_a_book_by_isbn_13():
        external_id = BookProviderIdentifier(BookProviderName.GOOGLE, "isbn13-book")
        await _book(external_id=external_id, isbn_13="9783161484100")

        found = await repo.find_by_isbn(isbn_10=None, isbn_13="9783161484100")

        assert found is not None
        assert found.isbn_13 == "9783161484100"

    async def it_returns_none_when_neither_isbn_is_given():
        assert await repo.find_by_isbn(isbn_10=None, isbn_13=None) is None

    async def it_returns_none_when_no_book_matches():
        assert await repo.find_by_isbn(isbn_10="0000000000", isbn_13=None) is None


def describe_find_by_id():
    async def it_finds_a_book_by_id():
        book = await _book(external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "find-by-id"))

        found = await repo.find_by_id(_id(book))

        assert found is not None
        assert found.title == "A Book"

    async def it_returns_none_when_the_book_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_id_by_identifier():
    async def it_resolves_by_external_id():
        external_id = BookProviderIdentifier(BookProviderName.GOOGLE, "resolve-by-external")
        book = await _book(external_id=external_id)

        found_id = await repo.find_id_by_identifier(external_id)

        assert found_id == _id(book)

    async def it_resolves_by_isbn():
        external_id = BookProviderIdentifier(BookProviderName.GOOGLE, "resolve-by-isbn")
        book = await _book(external_id=external_id, isbn_13="9783161484100")

        found_id = await repo.find_id_by_identifier("9783161484100")

        assert found_id == _id(book)

    async def it_returns_none_when_the_identifier_does_not_resolve():
        assert await repo.find_id_by_identifier("0000000000") is None


def describe_add_to_urls():
    async def it_merges_new_extensions_into_the_urls_map():
        book = await _book(external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "add-urls"))

        await repo.add_to_urls(_id(book), {ExtensionType.PDF: _https_url("https://example.com/book.pdf")})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert {ext: str(url) for ext, url in found.urls.items()} == {ExtensionType.PDF: "https://example.com/book.pdf"}

    async def it_does_not_clobber_existing_extensions():
        book = await _book(
            external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "add-urls-merge"),
            urls={ExtensionType.PDF: _https_url("https://example.com/existing.pdf")},
        )

        await repo.add_to_urls(_id(book), {ExtensionType.EPUB: _https_url("https://example.com/book.epub")})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert {ext: str(url) for ext, url in found.urls.items()} == {
            ExtensionType.PDF: "https://example.com/existing.pdf",
            ExtensionType.EPUB: "https://example.com/book.epub",
        }


def describe_fill_missing_fields():
    async def it_sets_the_given_fields():
        book = await _book(external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "fill-fields"))

        await repo.fill_missing_fields(_id(book), {"page_count": 350, "description": "A great read."})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert found.page_count == 350
        assert found.description == "A great read."


def describe_save():
    async def it_persists_changes_to_an_existing_book():
        book = await _book(external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "save-book"))

        book.title = "An Updated Title"
        await repo.save(book)

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert found.title == "An Updated Title"
