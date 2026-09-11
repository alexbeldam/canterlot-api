from dataclasses import dataclass
from datetime import datetime

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from canterlot.models.book import BookModel
from canterlot.models.read_book import RatingStats
from canterlot.pagination import Page, SortDirection
from canterlot.types import (
    AuthorList,
    BookExternalId,
    HttpsUrl,
    ISBN10Str,
    ISBN13Str,
    LanguageStr,
    NonEmptyStr,
    PageCount,
    PublishedYear,
    TitleStr,
    UrlList,
)


@dataclass(frozen=True)
class RatedBook:
    book: BookModel
    rating: float | None
    read_at: datetime


class RatedBookSummaryDTO(BaseModel):
    external_id: BookExternalId
    title: TitleStr
    authors: AuthorList
    cover_url: HttpsUrl | None = None
    rating: float | None = None

    @classmethod
    def from_model(cls, rated: RatedBook) -> "RatedBookSummaryDTO":
        return cls(
            external_id=rated.book.external_id,
            title=rated.book.title,
            authors=rated.book.authors,
            cover_url=rated.book.cover_url,
            rating=rated.rating,
        )


@dataclass
class ReadBooksFilters:
    page: int = Query(default=1, ge=1)
    limit: int = Query(default=20, ge=1, le=100)
    sort_direction: SortDirection = Query(default=SortDirection.DESC)  # noqa: RUF009


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


PaginatedBooksResponse = Page[BookSearchResult]


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
    average_rating: float | None = None
    rating_count: int = 0

    @classmethod
    def with_rating_stats(cls, book: BookModel, rating_stats: RatingStats) -> "BookResponse":
        base = cls.model_validate(book, from_attributes=True)
        return base.model_copy(
            update={"average_rating": rating_stats.average_rating, "rating_count": rating_stats.rating_count}
        )
