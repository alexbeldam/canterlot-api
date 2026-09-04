import pytest
from pydantic import ValidationError

from canterlot.models.book import BookModel, SearchParams


def describe_book_model():
    def it_requires_a_title():
        with pytest.raises(ValidationError):
            BookModel.model_validate({"external_id": "google-books__abc123"})

    def it_accepts_a_minimal_valid_document():
        book = BookModel.model_validate(
            {
                "external_id": "google-books__abc123",
                "title": "A Title",
                "cover_url": "https://example.com/c.jpg",
            }
        )
        assert book.authors == []
        assert book.urls == {}

    def it_defaults_the_cover_url_to_none_when_absent():
        book = BookModel.model_validate({"external_id": "google-books__abc123", "title": "A Title"})
        assert book.cover_url is None

    def it_rejects_a_blank_description():
        with pytest.raises(ValidationError):
            BookModel.model_validate({"external_id": "google-books__abc123", "title": "A Title", "description": "   "})


def describe_search_params_isbn_splitting():
    def it_populates_isbn_10_from_a_10_digit_isbn():
        params = SearchParams(isbn="0-306-40615-2")
        assert params.isbn_10 == "0306406152"
        assert params.isbn_13 is None

    def it_populates_isbn_13_from_a_13_digit_isbn():
        params = SearchParams(isbn="978-3-16-148410-0")
        assert params.isbn_10 is None
        assert params.isbn_13 == "9783161484100"

    def it_leaves_both_isbn_fields_none_when_no_isbn_is_given():
        params = SearchParams()
        assert params.isbn_10 is None
        assert params.isbn_13 is None

    def it_rejects_a_malformed_isbn():
        with pytest.raises(ValidationError):
            SearchParams(isbn="not-an-isbn")
