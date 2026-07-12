from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fastapi import Query
from pydantic import BaseModel, Field

from canterlot.dto.book import BookResponse
from canterlot.models.book import AuthorList, BookExternalId, BookModel, PageCount, PublishedYear, TitleStr
from canterlot.models.user import UsernameStr
from canterlot.pagination import Page, PageRequest
from canterlot.utils.format import HttpsUrl, ISBN10Str, ISBN13Str, LanguageStr, NonEmptyStr


class BookSuggestionRequest(BaseModel):
    source_id: BookExternalId
    title: TitleStr
    authors: AuthorList = Field(default_factory=list)
    year: PublishedYear | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    cover_url: HttpsUrl | None = None
    description: NonEmptyStr | None = Field(
        default=None,
        examples=[
            "A glorious high fantasy adventure following Bilbo Baggins as he journeys to reclaim a stolen treasure."
        ],
    )
    categories: list[NonEmptyStr] = Field(default_factory=list, examples=[["Fiction", "Fantasy"]])
    page_count: PageCount | None = None


class SuggestionStatus(StrEnum):
    ALREADY_EXISTS = "ALREADY_EXISTS"
    SUCCESS = "SUCCESS"


class SuggestionResponse(BaseModel):
    status: SuggestionStatus
    book_external_id: BookExternalId


class CatalogEntryResponse(BookResponse):
    suggested_by: UsernameStr
    suggested_at: datetime

    @classmethod
    def from_model(
        cls,
        book: BookModel,
        suggested_by: UsernameStr,
        suggested_at: datetime,
    ) -> "CatalogEntryResponse":
        base = BookResponse.model_validate(book, from_attributes=True)
        return cls(**base.model_dump(), suggested_by=suggested_by, suggested_at=suggested_at)


class CatalogSortField(StrEnum):
    SUGGESTED_AT = "suggested_at"
    TITLE = "title"
    AUTHOR = "author"
    YEAR = "year"


@dataclass
class CatalogFilters(PageRequest):
    sort_by: CatalogSortField | None = Query(default=None)  # noqa: RUF009 -- FastAPI sentinel, not mutable state
    suggested_by: UsernameStr | None = Query(default=None)  # noqa: RUF009 -- FastAPI sentinel, not mutable state


PaginatedCatalogResponse = Page[CatalogEntryResponse]
