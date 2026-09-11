from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar

from beanie import Document, Indexed
from pydantic import BaseModel, Field, model_validator
from pymongo import ASCENDING, IndexModel

from canterlot.types import (
    AuthorList,
    BookExternalId,
    BookProviderIdentifier,
    ExtensionType,
    HttpsUrl,
    ISBN10Str,
    ISBN13Str,
    ISBNStr,
    LanguageStr,
    NonEmptyStr,
    PageCount,
    PublishedYear,
    TitleStr,
    UrlList,
)
from canterlot.utils.isbn import split_isbn


class LinkCandidate(BaseModel):
    title: TitleStr
    authors: AuthorList
    languages: list[LanguageStr]
    extension: ExtensionType
    url: HttpsUrl


class BookModel(Document):
    external_id: Annotated[BookExternalId, Indexed(unique=True)]
    title: TitleStr
    authors: AuthorList = Field(default_factory=list)
    year: PublishedYear | None = None
    page_count: PageCount | None = None
    isbn_10: ISBN10Str | None = None
    isbn_13: ISBN13Str | None = None
    languages: list[LanguageStr] = Field(default_factory=list)
    description: NonEmptyStr | None = None
    categories: list[NonEmptyStr] = Field(default_factory=list)
    cover_url: HttpsUrl | None = None
    urls: UrlList = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "books"
        bson_encoders: ClassVar[dict[type, Any]] = {BookProviderIdentifier: str}
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [("isbn_10", ASCENDING)],
                unique=True,
                name="unique_isbn_10_idx",
                partialFilterExpression={"isbn_10": {"$type": "string"}},
            ),
            IndexModel(
                [("isbn_13", ASCENDING)],
                unique=True,
                name="unique_isbn_13_idx",
                partialFilterExpression={"isbn_13": {"$type": "string"}},
            ),
        ]


class SearchParams(BaseModel):
    title: TitleStr | None = None
    authors: AuthorList = Field(default_factory=list)
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
