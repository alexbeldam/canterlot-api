import pytest
from pydantic import ValidationError

from canterlot.dto.book import BookDetails, BookResponse, BookSearchResult, PaginatedBooksResponse
from canterlot.models.read_book import RatingStats
from tools.factories import BookFactory


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
        book = BookFactory.build()

        response = BookResponse.model_validate(book, from_attributes=True)

        assert response.title == book.title
        assert response.external_id == book.external_id
        assert not hasattr(response, "id")

    def it_defaults_rating_fields_to_none_and_zero():
        book = BookFactory.build()

        response = BookResponse.model_validate(book, from_attributes=True)

        assert response.average_rating is None
        assert response.rating_count == 0


def describe_book_response_with_rating_stats():
    def it_merges_rating_stats_into_the_base_response():
        book = BookFactory.build()
        stats = RatingStats(average_rating=4.0, rating_count=3)

        response = BookResponse.with_rating_stats(book, stats)

        assert response.title == book.title
        assert response.average_rating == 4.0
        assert response.rating_count == 3

    def it_keeps_average_rating_none_when_nobody_has_rated_it():
        book = BookFactory.build()
        stats = RatingStats(average_rating=None, rating_count=0)

        response = BookResponse.with_rating_stats(book, stats)

        assert response.average_rating is None
        assert response.rating_count == 0
