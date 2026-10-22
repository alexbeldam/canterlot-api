from pydantic import validate_call

from canterlot.text import ISBN10_LEN
from canterlot.types import ISBN10Str, ISBN13Str, ISBNStr


@validate_call
def split_isbn(isbn: ISBNStr) -> tuple[ISBN10Str | None, ISBN13Str | None]:
    if len(isbn) == ISBN10_LEN:
        return isbn, None
    return None, isbn
