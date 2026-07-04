from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import ClubSuggestionsClosedError, UnauthorizedClubMemberError
from canterlot.models.book import LinkCandidate
from canterlot.models.catalog import BookSuggestionRequest, SuggestionStatus
from canterlot.models.enums import BookProviderName, ExtensionType
from canterlot.services.catalog import CatalogService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _suggestion(**overrides) -> BookSuggestionRequest:
    defaults = {
        "source_id": "ext-1",
        "provider": BookProviderName.GOOGLE,
        "title": "The Hobbit",
        "authors": ["J.R.R. Tolkien"],
        "cover_url": "https://example.com/c.jpg",
        "description": "A hobbit's tale",
        "languages": ["en"],
    }
    return BookSuggestionRequest.model_validate({**defaults, **overrides})


def _candidate(**overrides) -> LinkCandidate:
    defaults = {
        "title": "The Hobbit",
        "authors": ["J.R.R. Tolkien"],
        "language": "en",
        "extension": ExtensionType.PDF,
        "url": "https://mirror.example.com/hobbit.pdf",
    }
    return LinkCandidate.model_validate({**defaults, **overrides})


def _existing_book(urls: dict | None = None) -> AsyncMock:
    book = AsyncMock()
    book.id = SOME_BOOK_ID
    book.urls = urls or {}
    return book


def _service(book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock) -> CatalogService:
    link_provider.name = "annas-archive"
    return CatalogService(book_repo, club_repo, [link_provider])


def describe_membership_and_suggestion_gating():
    async def it_rejects_a_non_member(book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = _service(book_repo, club_repo, link_provider)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        club_repo.is_suggestions_allowed.assert_not_called()

    async def it_rejects_a_suggestion_when_the_queue_is_closed(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = False
        service = _service(book_repo, club_repo, link_provider)

        with pytest.raises(ClubSuggestionsClosedError):
            await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())


def describe_suggesting_a_new_book():
    async def it_scrapes_all_formats_creates_and_catalogs_a_new_book(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.return_value = [_candidate()]

        saved_book = _existing_book(urls={ExtensionType.PDF: "https://mirror.example.com/hobbit.pdf"})

        async def fake_save(_book):
            saved_book.id = SOME_BOOK_ID
            return saved_book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.SUCCESS
        book_repo.save.assert_awaited_once()
        club_repo.add_to_catalog.assert_awaited_once()


def describe_suggesting_an_existing_book():
    async def it_returns_already_exists_without_scraping_when_all_formats_are_present_and_linked(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        book_repo.find_by_provider_and_provider_book_id.return_value = _existing_book(urls=complete_urls)
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.ALREADY_EXISTS
        link_provider.find_links.assert_not_called()
        club_repo.add_to_catalog.assert_not_called()

    async def it_scrapes_missing_formats_and_supplements_the_existing_book(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = _existing_book(urls={})
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = False
        link_provider.find_links.return_value = [_candidate()]
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.SUCCESS
        book_repo.add_to_urls.assert_awaited_once()
        club_repo.add_to_catalog.assert_awaited_once()

    async def it_does_not_touch_urls_when_scraping_finds_nothing_new(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = _existing_book(urls={})
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = False
        link_provider.find_links.return_value = []
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        book_repo.add_to_urls.assert_not_called()


def describe_link_candidate_scoring():
    async def it_discards_candidates_below_the_similarity_threshold(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.return_value = [
            _candidate(title="Completely Unrelated Text", authors=["Someone Else"])
        ]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert captured["book"].urls == {}

    async def it_excludes_candidates_whose_language_does_not_match_preferred_languages(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.return_value = [_candidate(language="pt-BR")]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=["en"]))

        assert captured["book"].urls == {}

    async def it_does_not_filter_by_language_when_no_preferred_languages_are_given(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.return_value = [_candidate(language="pt-BR")]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=[]))

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/hobbit.pdf"

    async def it_ignores_a_link_provider_that_raises(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.side_effect = RuntimeError("scraper is down")

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.SUCCESS
        assert captured["book"].urls == {}

    async def it_ignores_a_link_provider_returning_an_unexpected_payload_shape(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_provider_and_provider_book_id.return_value = None
        link_provider.find_links.return_value = "not-a-list"

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert captured["book"].urls == {}
