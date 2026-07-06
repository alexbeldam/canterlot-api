from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from canterlot.models.book import (
    AuthorList,
    BookExternalId,
    PageCount,
    PublishedYear,
    TitleStr,
    UrlList,
)
from canterlot.utils.format import HttpsUrl, ISBN10Str, ISBN13Str, LanguageStr, NonEmptyStr


class BookSearchResult(BaseModel):
    id: BookExternalId
    title: TitleStr
    authors: AuthorList = Field(default_factory=list)
    year: PublishedYear | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    cover_url: HttpsUrl | None = None


class BookDetails(BaseModel):
    page_count: PageCount | None = None
    description: NonEmptyStr | None = Field(
        default=None,
        examples=[
            "A glorious high fantasy adventure following Bilbo Baggins as he journeys to reclaim a stolen treasure."
        ],
    )
    categories: list[NonEmptyStr] = Field(default_factory=list, examples=[["Fiction", "Fantasy", "High Fantasy"]])


class PaginatedBooksResponse(BaseModel):
    books: list[BookSearchResult]
    total_pages: int = Field(ge=0, examples=[1])
    current_page: int = Field(ge=1)
    total_results: int = Field(ge=0, examples=[1])


class BookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: BookExternalId
    title: TitleStr
    authors: AuthorList = Field(default_factory=list)
    year: PublishedYear | None = None
    page_count: PageCount | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    description: NonEmptyStr | None = Field(
        default=None,
        examples=[
            "A glorious high fantasy adventure following Bilbo Baggins as he journeys to reclaim a stolen treasure."
        ],
    )
    categories: list[NonEmptyStr] = Field(default_factory=list, examples=[["Fiction", "Fantasy", "High Fantasy"]])
    cover_url: HttpsUrl | None = None
    urls: UrlList = Field(default_factory=dict)
    created_at: datetime
