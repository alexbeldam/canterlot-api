import pytest
from pydantic import ValidationError

from canterlot.dto.catalog import BookSuggestionRequest, SuggestionResponse, SuggestionStatus
from canterlot.models.book import BookProviderIdentifier
from canterlot.models.enums import BookProviderName


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
