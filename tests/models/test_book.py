from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from canterlot.models.book import (
    MIN_PUBLISHED_YEAR,
    BookModel,
    BookProviderIdentifier,
    PublishedYear,
    SearchParams,
    validate_published_year,
)
from canterlot.models.enums import BookProviderName

published_year_adapter: TypeAdapter[PublishedYear] = TypeAdapter(PublishedYear)


def describe_validate_published_year():
    def it_accepts_a_reasonable_year():
        assert validate_published_year(2020) == 2020

    def it_rejects_years_before_the_minimum():
        with pytest.raises(ValueError, match="cannot be earlier"):
            validate_published_year(MIN_PUBLISHED_YEAR - 1)

    def it_accepts_the_minimum_year_itself():
        assert validate_published_year(MIN_PUBLISHED_YEAR) == MIN_PUBLISHED_YEAR

    def it_rejects_years_too_far_in_the_future():
        max_allowed = datetime.now().year + 2
        with pytest.raises(ValueError, match="cannot be further in the future"):
            validate_published_year(max_allowed + 1)

    def it_accepts_the_maximum_allowed_future_year():
        max_allowed = datetime.now().year + 2
        assert published_year_adapter.validate_python(max_allowed) == max_allowed


def describe_book_provider_identifier():
    def it_round_trips_through_string_serialization():
        adapter = TypeAdapter(BookProviderIdentifier)
        identifier = adapter.validate_python("google-books__zyTCAlFlgZ8C")

        assert identifier.provider == BookProviderName.GOOGLE
        assert identifier.book_id == "zyTCAlFlgZ8C"
        assert str(identifier) == "google-books__zyTCAlFlgZ8C"

    def it_rejects_a_string_missing_the_separator():
        adapter = TypeAdapter(BookProviderIdentifier)
        with pytest.raises(ValidationError):
            adapter.validate_python("no-separator-here")

    def it_rejects_an_unknown_provider_segment():
        adapter = TypeAdapter(BookProviderIdentifier)
        with pytest.raises(ValidationError):
            adapter.validate_python("not-a-provider__abc123")


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
