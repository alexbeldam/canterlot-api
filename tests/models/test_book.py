from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from canterlot.models.book import (
    MIN_PUBLISHED_YEAR,
    BookDetails,
    BookModel,
    BookSearchResult,
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


def describe_book_search_result():
    def it_defaults_the_cover_url_to_none_when_absent():
        result = BookSearchResult.model_validate({"id": "x", "provider": BookProviderName.GOOGLE, "title": "A Title"})
        assert result.cover_url is None

    def it_rejects_a_plain_http_cover_url():
        with pytest.raises(ValidationError):
            BookSearchResult.model_validate(
                {
                    "id": "x",
                    "provider": BookProviderName.GOOGLE,
                    "title": "A Title",
                    "cover_url": "http://example.com/c.jpg",
                }
            )

    def it_accepts_a_minimal_valid_result():
        result = BookSearchResult.model_validate(
            {
                "id": "x",
                "provider": BookProviderName.GOOGLE,
                "title": "A Title",
                "cover_url": "https://example.com/c.jpg",
            }
        )
        assert result.authors == []
        assert result.languages == []
        assert result.year is None


def describe_book_model():
    def it_requires_a_title_and_cover_url():
        with pytest.raises(ValidationError):
            BookModel.model_validate({"provider": BookProviderName.GOOGLE})

    def it_accepts_a_minimal_valid_document():
        book = BookModel.model_validate(
            {
                "provider": BookProviderName.GOOGLE,
                "title": "A Title",
                "cover_url": "https://example.com/c.jpg",
            }
        )
        assert book.authors == []
        assert book.urls == {}


def describe_book_details():
    def it_defaults_page_count_and_description_to_none():
        details = BookDetails.model_validate({})
        assert details.page_count is None
        assert details.description is None
        assert details.categories == []

    def it_rejects_a_blank_description():
        with pytest.raises(ValidationError):
            BookDetails.model_validate({"description": "   "})


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
