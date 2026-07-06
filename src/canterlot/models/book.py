from datetime import UTC, datetime
from typing import Annotated, Any

from beanie import Document, Indexed, PydanticObjectId
from pydantic import AfterValidator, BaseModel, Field, GetCoreSchemaHandler, StringConstraints, model_validator
from pydantic_core import CoreSchema, core_schema

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


type UrlList = Annotated[
    dict[ExtensionType, HttpsUrl],
    Field(
        json_schema_extra={
            "examples": [
                {
                    "pdf": "https://example.com/book.pdf",
                    "epub": "https://example.com/book.epub",
                }
            ]
        }
    ),
]
type PublishedYear = Annotated[
    int,
    AfterValidator(validate_published_year),
    Field(examples=[1998, 2025]),
]
type TitleStr = Annotated[
    NonEmptyStr,
    StringConstraints(max_length=200),
    Field(examples=["The Hobbit", "A Game of Thrones"]),
]
type AuthorList = Annotated[
    list[NonEmptyStr],
    Field(
        examples=[
            ["J.R.R. Tolkien"],
            ["George R.R. Martin", "Fire & Blood Editorial Team"],
        ],
    ),
]
type PageCount = Annotated[int, Field(ge=0, examples=[310, 700])]


class BookProviderIdentifier:
    def __init__(self, provider: BookProviderName, book_id: str):
        self.provider = provider
        self.book_id = book_id

    def __repr__(self) -> str:
        return f"ProviderIdentifier(provider='{self.provider}', id='{self.book_id}')"

    def __str__(self) -> str:
        return f"{self.provider}__{self.book_id}"

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        def validate(value: Any) -> BookProviderIdentifier:
            if isinstance(value, cls):
                return value
            if isinstance(value, str):
                if "__" not in value:
                    raise ValueError("Identifier must follow the 'provider__id' format")
                provider, provider_book_id = value.split("__", 1)
                if not provider or not provider_book_id:
                    raise ValueError("Both provider and id segments must be non-empty strings")
                try:
                    provider_name = BookProviderName(provider)
                except ValueError:
                    raise ValueError("Provider segment must be a valid name") from None
                return cls(provider_name, provider_book_id)
            raise ValueError("Input must be a string or an instance of ProviderIdentifier")

        def serialize(instance: BookProviderIdentifier) -> str:
            return str(instance)

        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_plain_validator_function(
                validate, json_schema_input_schema=core_schema.str_schema()
            ),
            python_schema=core_schema.no_info_plain_validator_function(validate),
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, return_schema=core_schema.str_schema()
            ),
        )


type BookExternalId = Annotated[
    BookProviderIdentifier,
    Field(
        description=(
            "The unique, URL-safe external identifier combining the source provider name "
            "and their asset ID, separated by a double underscore. Format: 'provider__id'."
        ),
        examples=["google-books__zyTCAlFlgZ8C"],
    ),
]


class LinkCandidate(BaseModel):
    title: TitleStr
    authors: AuthorList
    languages: list[LanguageStr]
    extension: ExtensionType
    url: HttpsUrl


class ReadBook(BaseModel):
    id: PydanticObjectId
    read_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
