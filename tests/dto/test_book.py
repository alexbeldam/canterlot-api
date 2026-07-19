from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from canterlot.dto.book import BookDetails, BookResponse, BookSearchResult, PaginatedBooksResponse
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.types import BookProviderName


def describe_book_search_result():
    def it_defaults_the_cover_url_to_none_when_absent():
        result = BookSearchResult.model_validate({"id": "google-books__x", "title": "A Title"})
        assert result.cover_url is None

    def it_rejects_a_plain_http_cover_url():
        with pytest.raises(ValidationError):
            BookSearchResult.model_validate(
                {
                    "id": "google-books__x",
                    "title": "A Title",
                    "cover_url": "http://example.com/c.jpg",
                }
            )

    def it_accepts_a_minimal_valid_result():
        result = BookSearchResult.model_validate(
            {
                "id": "google-books__x",
                "title": "A Title",
                "cover_url": "https://example.com/c.jpg",
            }
        )
        assert result.authors == []
        assert result.languages == []
        assert result.year is None


def describe_book_details():
    def it_defaults_page_count_and_description_to_none():
        details = BookDetails.model_validate({})
        assert details.page_count is None
        assert details.description is None
        assert details.categories == []

    def it_rejects_a_blank_description():
        with pytest.raises(ValidationError):
            BookDetails.model_validate({"description": "   "})


def describe_paginated_books_response():
    def it_accepts_an_empty_page():
        response = PaginatedBooksResponse(items=[], total_items=0, current_page=1, page_size=20)
        assert response.items == []


def describe_book_response():
    def it_builds_from_a_book_model_without_exposing_the_internal_id():
        book = BookModel(
            external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "abc123"),
            title="The Hobbit",
            created_at=datetime.now(UTC),
        )

        response = BookResponse.model_validate(book, from_attributes=True)

        assert response.title == "The Hobbit"
        assert str(response.external_id) == "google-books__abc123"
        assert not hasattr(response, "id")
