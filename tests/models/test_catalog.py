import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from canterlot.models.catalog import BookSuggestionRequest, SuggestionResponse, SuggestionStatus
from canterlot.models.enums import BookProviderName


def describe_book_suggestion_request():
    def it_requires_a_title():
        with pytest.raises(ValidationError):
            BookSuggestionRequest.model_validate({"source_id": "x", "provider": BookProviderName.GOOGLE})

    def it_defaults_the_description_to_none_when_absent():
        suggestion = BookSuggestionRequest.model_validate(
            {"source_id": "x", "provider": BookProviderName.GOOGLE, "title": "A Title"}
        )
        assert suggestion.description is None

    def it_accepts_a_minimal_valid_suggestion():
        suggestion = BookSuggestionRequest.model_validate(
            {
                "source_id": "x",
                "provider": BookProviderName.GOOGLE,
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
                "source_id": "x",
                "provider": BookProviderName.GOOGLE,
                "title": "A Title",
                "description": "A description",
            }
        )
        assert suggestion.cover_url is None

    def it_rejects_a_blank_description():
        with pytest.raises(ValidationError):
            BookSuggestionRequest.model_validate(
                {
                    "source_id": "x",
                    "provider": BookProviderName.GOOGLE,
                    "title": "A Title",
                    "description": "   ",
                }
            )


def describe_suggestion_response():
    def it_carries_the_status_and_book_id():
        response = SuggestionResponse(status=SuggestionStatus.SUCCESS, book_id=PydanticObjectId())
        assert response.status == SuggestionStatus.SUCCESS
