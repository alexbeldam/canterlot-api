import re
from difflib import SequenceMatcher
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    StringConstraints,
    UrlConstraints,
    validate_call,
)

from .language import normalize_language

ISBN10_LEN = 10
ISBN13_LEN = 13


def normalize_isbn(isbn_str: str) -> str:
    cleaned = re.sub(r"[^0-9Xx]", "", isbn_str)

    if len(cleaned) not in [ISBN10_LEN, ISBN13_LEN]:
        raise ValueError(f"{isbn_str!r} is not a valid ISBN")

    return cleaned.upper()


def normalize_email(email: str) -> str:
    return email.strip().lower()


type LanguageStr = Annotated[str, AfterValidator(normalize_language)]
type ISBNStr = Annotated[str, BeforeValidator(normalize_isbn)]
type ISBN10Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN10_LEN, max_length=ISBN10_LEN)]
type ISBN13Str = Annotated[ISBNStr, StringConstraints(min_length=ISBN13_LEN, max_length=ISBN13_LEN)]
type HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]
type NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type NormalizedEmailStr = Annotated[EmailStr, BeforeValidator(normalize_email)]


@validate_call
def split_isbn(isbn: ISBNStr) -> tuple[ISBN10Str | None, ISBN13Str | None]:
    if len(isbn) == ISBN10_LEN:
        return isbn, None
    return None, isbn


def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
