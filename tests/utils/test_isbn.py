import pytest
from pydantic import ValidationError

from canterlot.utils.isbn import split_isbn


def describe_split_isbn():
    def it_splits_an_isbn10_correctly():
        isbn10, isbn13 = split_isbn("0_306_40615_x")
        assert isbn10 == "030640615X"
        assert isbn13 is None

    def it_splits_an_isbn13_correctly():
        isbn10, isbn13 = split_isbn("978-3-16-148410-0")
        assert isbn10 is None
        assert isbn13 == "9783161484100"

    def it_validates_and_fails_on_bad_input():
        with pytest.raises(ValidationError):
            split_isbn("not-an-isbn")
