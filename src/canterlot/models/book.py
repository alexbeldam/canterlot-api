from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, PydanticObjectId
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from canterlot.models.enums import BookProviderName, ExtensionType
from canterlot.utils.format import HttpsUrl, ISBN10Str, ISBN13Str, ISBNStr, LanguageStr, NonEmptyStr, split_isbn

MIN_PUBLISHED_YEAR = 868  # Diamond Sutra publication date


def validate_published_year(v: int) -> int:
    max_allowed_year = datetime.now().year + 2

    if v < MIN_PUBLISHED_YEAR:
        raise ValueError(f"Year cannot be earlier than {MIN_PUBLISHED_YEAR}")
    if v > max_allowed_year:
        raise ValueError(f"Year cannot be further in the future than {max_allowed_year}")

    return v


type UrlList = dict[ExtensionType, HttpsUrl]
type PublishedYear = Annotated[int, AfterValidator(validate_published_year)]
type TitleStr = Annotated[NonEmptyStr, StringConstraints(max_length=200)]


class LinkCandidate(BaseModel):
    title: TitleStr
    authors: list[NonEmptyStr]
    language: LanguageStr
    extension: ExtensionType
    url: HttpsUrl


class BookSearchResult(BaseModel):
    id: str = Field(..., description="The unique ID from the external provider")
    provider: BookProviderName = Field(..., description="The name of the source provider (e.g., 'google-books')")
    title: TitleStr
    authors: list[NonEmptyStr] = Field(default_factory=list)
    year: PublishedYear | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    cover_url: HttpsUrl | None = None


class BookDetails(BaseModel):
    page_count: int | None = Field(default=None, ge=0)
    description: NonEmptyStr | None = None
    categories: list[NonEmptyStr] = Field(default_factory=list)


class PaginatedBooksResponse(BaseModel):
    books: list[BookSearchResult]
    total_pages: int = Field(ge=0)
    current_page: int = Field(ge=1)
    total_results: int = Field(ge=0)


class ReadBook(BaseModel):
    id: PydanticObjectId
    read_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BookModel(Document):
    provider: BookProviderName
    provider_book_id: str | None = Field(None, description="The unique identifier from the external provider source")
    title: TitleStr
    authors: list[NonEmptyStr] = Field(default_factory=list)
    year: PublishedYear | None = None
    page_count: int | None = Field(None, ge=0)
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    categories: list[NonEmptyStr] = Field(default_factory=list)
    cover_url: HttpsUrl
    urls: UrlList = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "books"


class SearchParams(BaseModel):
    title: TitleStr | None = None
    authors: list[NonEmptyStr] = Field(default_factory=list)
    isbn: ISBNStr | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    extensions: list[ExtensionType] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_isbns(self):
        if self.isbn:
            self.isbn_10, self.isbn_13 = split_isbn(self.isbn)
        return self
