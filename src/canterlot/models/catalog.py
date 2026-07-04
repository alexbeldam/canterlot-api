from enum import StrEnum

from beanie import PydanticObjectId
from pydantic import BaseModel, Field

from canterlot.models.book import AuthorList, PageCount, PublishedYear, TitleStr
from canterlot.models.enums import BookProviderName
from canterlot.utils.format import HttpsUrl, ISBN10Str, ISBN13Str, LanguageStr, NonEmptyStr


class BookSuggestionRequest(BaseModel):
    source_id: str = Field(..., description="The ID returned by the search endpoint", examples=["zyTCAlFlgZ8C"])
    provider: BookProviderName
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
    book_id: PydanticObjectId
