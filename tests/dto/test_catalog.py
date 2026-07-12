from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from canterlot.dto.catalog import BookSuggestionRequest, CatalogEntryResponse, SuggestionResponse, SuggestionStatus
from canterlot.models.book import BookModel, BookProviderIdentifier
from canterlot.models.enums import BookProviderName


def _book_document(**overrides) -> BookModel:
    defaults = {
        "external_id": BookProviderIdentifier(BookProviderName.GOOGLE, "abc123"),
        "title": "The Hobbit",
        "created_at": datetime.now(UTC),
    }
    return BookModel(**{**defaults, **overrides})


def describe_book_suggestion_request():
    def it_requires_a_title():
        with pytest.raises(ValidationError):
            BookSuggestionRequest.model_validate({"source_id": "google-books__x"})

    def it_defaults_the_description_to_none_when_absent():
        suggestion = BookSuggestionRequest.model_validate({"source_id": "google-books__x", "title": "A Title"})
        assert suggestion.description is None

    def it_accepts_a_minimal_valid_suggestion():
        suggestion = BookSuggestionRequest.model_validate(
            {
                "source_id": "google-books__x",
                "title": "A Title",
                "cover_url": "https://example.com/c.jpg",
                "description": "A description",
            }
        )
        assert suggestion.authors == []
        assert suggestion.categories == []

    def it_defaults_the_cover_url_to_none_when_absent():
        suggestion = BookSuggestionRequest.model_validate(
            {
                "source_id": "google-books__x",
                "title": "A Title",
                "description": "A description",
            }
        )
        assert suggestion.cover_url is None

    def it_rejects_a_blank_description():
        with pytest.raises(ValidationError):
            BookSuggestionRequest.model_validate(
                {
                    "source_id": "google-books__x",
                    "title": "A Title",
                    "description": "   ",
                }
            )

    def it_rejects_a_source_id_missing_the_provider_prefix():
        with pytest.raises(ValidationError):
            BookSuggestionRequest.model_validate({"source_id": "x", "title": "A Title"})


def describe_suggestion_response():
    def it_carries_the_status_and_book_external_id():
        response = SuggestionResponse(
            status=SuggestionStatus.SUCCESS,
            book_external_id=BookProviderIdentifier(BookProviderName.GOOGLE, "x"),
        )
        assert response.status == SuggestionStatus.SUCCESS
        assert str(response.book_external_id) == "google-books__x"


def describe_catalog_entry_response():
    def it_builds_from_a_book_model_plus_suggestion_metadata():
        book = _book_document()
        suggested_at = datetime.now(UTC)

        entry = CatalogEntryResponse.from_model(book, suggested_by="twilight_sparkle", suggested_at=suggested_at)

        assert entry.title == "The Hobbit"
        assert str(entry.external_id) == "google-books__abc123"
        assert entry.suggested_by == "twilight_sparkle"
        assert entry.suggested_at == suggested_at

    def it_does_not_expose_the_internal_book_id():
        entry = CatalogEntryResponse.from_model(
            _book_document(), suggested_by="twilight_sparkle", suggested_at=datetime.now(UTC)
        )

        assert not hasattr(entry, "id")
