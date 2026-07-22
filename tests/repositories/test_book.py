from collections.abc import Callable

import pytest
from beanie import PydanticObjectId
from pydantic import TypeAdapter

from canterlot.factories import BookFactory
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.repositories.beanie.book import BeanieBookRepository
from canterlot.types import BookProviderName, ExtensionType, HttpsUrl

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieBookRepository()
_https_url: Callable[[str], HttpsUrl] = TypeAdapter(HttpsUrl).validate_python


def _id(book: BookModel) -> PydanticObjectId:
    return PydanticObjectId(book.id)


def describe_find_by_external_id():
    async def it_finds_a_book_by_external_id():
        book = await BookFactory.create_async()

        found = await repo.find_by_external_id(book.external_id)

        assert found is not None
        assert found.title == book.title

    async def it_returns_none_when_no_book_matches():
        missing = BookProviderIdentifier(BookProviderName.GOOGLE, BookFactory.__faker__.bothify("????####"))

        assert await repo.find_by_external_id(missing) is None


def describe_find_by_isbn():
    async def it_finds_a_book_by_isbn_10():
        isbn_10 = BookFactory.__faker__.isbn10(separator="")
        book = await BookFactory.create_async(isbn_10=isbn_10)

        found = await repo.find_by_isbn(isbn_10=isbn_10, isbn_13=None)

        assert found is not None
        assert found.isbn_10 == book.isbn_10

    async def it_finds_a_book_by_isbn_13():
        isbn_13 = BookFactory.__faker__.isbn13(separator="")
        book = await BookFactory.create_async(isbn_13=isbn_13)

        found = await repo.find_by_isbn(isbn_10=None, isbn_13=isbn_13)

        assert found is not None
        assert found.isbn_13 == book.isbn_13

    async def it_returns_none_when_neither_isbn_is_given():
        assert await repo.find_by_isbn(isbn_10=None, isbn_13=None) is None

    async def it_returns_none_when_no_book_matches():
        unregistered_isbn = BookFactory.__faker__.isbn10(separator="")
        assert await repo.find_by_isbn(isbn_10=unregistered_isbn, isbn_13=None) is None


def describe_find_by_id():
    async def it_finds_a_book_by_id():
        book = await BookFactory.create_async()

        found = await repo.find_by_id(_id(book))

        assert found is not None
        assert found.title == book.title

    async def it_returns_none_when_the_book_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_by_ids():
    async def it_maps_ids_to_books():
        first = await BookFactory.create_async()
        second = await BookFactory.create_async()

        found = await repo.find_by_ids([_id(first), _id(second)])

        assert found.keys() == {_id(first), _id(second)}
        assert found[_id(first)].title == first.title

    async def it_returns_an_empty_dict_for_an_empty_list():
        assert await repo.find_by_ids([]) == {}


def describe_find_id_by_identifier():
    async def it_resolves_by_external_id():
        book = await BookFactory.create_async()

        found_id = await repo.find_id_by_identifier(book.external_id)

        assert found_id == _id(book)

    async def it_resolves_by_isbn():
        isbn_13 = BookFactory.__faker__.isbn13(separator="")
        book = await BookFactory.create_async(isbn_13=isbn_13)

        found_id = await repo.find_id_by_identifier(isbn_13)

        assert found_id == _id(book)

    async def it_returns_none_when_the_identifier_does_not_resolve():
        unregistered_isbn = BookFactory.__faker__.isbn10(separator="")
        assert await repo.find_id_by_identifier(unregistered_isbn) is None


def describe_add_to_urls():
    async def it_merges_new_extensions_into_the_urls_map():
        book = await BookFactory.create_async(urls={})
        pdf_url_str = f"https://example.com/{BookFactory.__faker__.file_name(category='document', extension='pdf')}"

        await repo.add_to_urls(_id(book), {ExtensionType.PDF: _https_url(pdf_url_str)})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert {ext: str(url) for ext, url in found.urls.items()} == {ExtensionType.PDF: pdf_url_str}

    async def it_does_not_clobber_existing_extensions():
        existing_pdf_url_str = (
            f"https://example.com/{BookFactory.__faker__.file_name(category='document', extension='pdf')}"
        )
        new_epub_url_str = (
            f"https://example.com/{BookFactory.__faker__.file_name(category='document', extension='epub')}"
        )

        book = await BookFactory.create_async(
            urls={ExtensionType.PDF: _https_url(existing_pdf_url_str)},
        )

        await repo.add_to_urls(_id(book), {ExtensionType.EPUB: _https_url(new_epub_url_str)})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert {ext: str(url) for ext, url in found.urls.items()} == {
            ExtensionType.PDF: existing_pdf_url_str,
            ExtensionType.EPUB: new_epub_url_str,
        }


def describe_fill_missing_fields():
    async def it_sets_the_given_fields():
        book = await BookFactory.create_async(page_count=None, description=None)
        new_page_count = BookFactory.__faker__.random_int(min=100, max=500)
        new_description = BookFactory.__faker__.paragraph()

        await repo.fill_missing_fields(_id(book), {"page_count": new_page_count, "description": new_description})

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert found.page_count == new_page_count
        assert found.description == new_description


def describe_save():
    async def it_persists_changes_to_an_existing_book():
        book = await BookFactory.create_async()
        updated_title = BookFactory.__faker__.sentence(nb_words=3)

        book.title = updated_title
        await repo.save(book)

        found = await repo.find_by_id(_id(book))
        assert found is not None
        assert found.title == updated_title


def describe_find_by_identifier():
    async def it_finds_book_by_external_id_identifier():
        book = await BookFactory.create_async()

        found = await repo.find_by_identifier(book.external_id)

        assert found is not None
        assert found.title == book.title

    async def it_finds_book_by_isbn_identifier():
        isbn_13 = BookFactory.__faker__.isbn13(separator="")
        book = await BookFactory.create_async(isbn_13=isbn_13)

        found = await repo.find_by_identifier(isbn_13)

        assert found is not None
        assert found.title == book.title

    async def it_returns_none_when_identifier_does_not_exist():
        unregistered_isbn = BookFactory.__faker__.isbn13(separator="")
        assert await repo.find_by_identifier(unregistered_isbn) is None
