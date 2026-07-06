from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.catalog import BookSuggestionRequest, SuggestionStatus
from canterlot.exceptions import ClubSuggestionsClosedError, UnauthorizedClubMemberError
from canterlot.models.book import LinkCandidate
from canterlot.models.enums import ExtensionType, LinkProviderName
from canterlot.services.catalog import CatalogService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _suggestion(**overrides) -> BookSuggestionRequest:
    defaults = {
        "source_id": "google-books__ext-1",
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
        "languages": ["en"],
        "extension": ExtensionType.PDF,
        "url": "https://mirror.example.com/hobbit.pdf",
    }
    return LinkCandidate.model_validate({**defaults, **overrides})


def _existing_book(urls: dict | None = None, **overrides) -> AsyncMock:
    book = AsyncMock()
    book.id = SOME_BOOK_ID
    book.external_id = overrides.get("external_id", "google-books__existing-book")
    book.urls = urls or {}
    book.year = overrides.get("year")
    book.page_count = overrides.get("page_count")
    book.isbn_10 = overrides.get("isbn_10")
    book.isbn_13 = overrides.get("isbn_13")
    book.description = overrides.get("description")
    book.cover_url = overrides.get("cover_url")
    book.authors = overrides.get("authors", [])
    book.categories = overrides.get("categories", [])
    book.languages = overrides.get("languages", [])
    return book


def _service(book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock) -> CatalogService:
    link_provider.name = LinkProviderName.ANNAS
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
        book_repo.find_by_external_id.return_value = None
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

    async def it_persists_the_description_onto_the_new_book(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        link_provider.find_links.return_value = []

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert captured["book"].description == "A hobbit's tale"


def describe_suggesting_an_existing_book():
    async def it_returns_already_exists_without_scraping_when_all_formats_are_present_and_linked(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        book_repo.find_by_external_id.return_value = _existing_book(urls=complete_urls)
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
        book_repo.find_by_external_id.return_value = _existing_book(urls={})
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = False
        link_provider.find_links.return_value = [_candidate()]
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.SUCCESS
        book_repo.add_to_urls.assert_awaited_once()
        club_repo.add_to_catalog.assert_awaited_once()

    async def it_finds_an_existing_book_by_isbn_before_falling_back_to_provider_and_source_id(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        book_repo.find_by_isbn.return_value = _existing_book(urls=complete_urls)
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(isbn_10="0261102214"))

        assert result.status == SuggestionStatus.ALREADY_EXISTS
        book_repo.find_by_isbn.assert_awaited_once_with("0261102214", None)
        book_repo.find_by_external_id.assert_not_called()

    async def it_falls_back_to_provider_and_source_id_when_no_book_matches_the_isbn(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        book_repo.find_by_isbn.return_value = None
        book_repo.find_by_external_id.return_value = _existing_book(urls=complete_urls)
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(isbn_10="0261102214"))

        assert result.status == SuggestionStatus.ALREADY_EXISTS
        book_repo.find_by_isbn.assert_awaited_once_with("0261102214", None)
        book_repo.find_by_external_id.assert_awaited_once()

    async def it_skips_the_isbn_lookup_when_the_suggestion_has_no_isbn(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        book_repo.find_by_external_id.return_value = _existing_book(urls=complete_urls)
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        result = await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert result.status == SuggestionStatus.ALREADY_EXISTS
        book_repo.find_by_isbn.assert_not_called()

    async def it_does_not_touch_urls_when_scraping_finds_nothing_new(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = _existing_book(urls={})
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = False
        link_provider.find_links.return_value = []
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        book_repo.add_to_urls.assert_not_called()


def describe_backfilling_missing_metadata():
    async def it_fills_missing_scalar_fields_from_the_suggestion(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        existing = _existing_book(urls=complete_urls, authors=["Existing Author"], languages=["en"])
        book_repo.find_by_external_id.return_value = existing
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        book_repo.fill_missing_fields.assert_awaited_once()
        book_id, updates = book_repo.fill_missing_fields.call_args.args
        assert book_id == SOME_BOOK_ID
        assert updates.keys() == {"description", "cover_url"}
        assert updates["description"] == "A hobbit's tale"
        assert str(updates["cover_url"]) == "https://example.com/c.jpg"

    async def it_fills_an_empty_list_field_from_the_suggestion(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        existing = _existing_book(
            urls=complete_urls,
            cover_url="https://existing.example.com/c.jpg",
            description="Existing description",
            languages=["en"],
        )
        book_repo.find_by_external_id.return_value = existing
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        book_repo.fill_missing_fields.assert_awaited_once_with(SOME_BOOK_ID, {"authors": ["J.R.R. Tolkien"]})

    async def it_does_not_touch_a_list_field_that_already_has_entries(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        existing = _existing_book(urls=complete_urls, authors=["Existing Author"], languages=["en"])
        book_repo.find_by_external_id.return_value = existing
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(
            SOME_CLUB_ID, SOME_USER_ID, _suggestion(authors=["J.R.R. Tolkien", "A Co-Author"])
        )

        updates = book_repo.fill_missing_fields.call_args.args[1]
        assert "authors" not in updates

    async def it_does_not_call_fill_missing_fields_when_nothing_is_missing(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        complete_urls = dict.fromkeys(ExtensionType, "https://example.com/x")
        existing = _existing_book(
            urls=complete_urls,
            authors=["Existing Author"],
            languages=["en"],
            cover_url="https://existing.example.com/c.jpg",
            description="Existing description",
        )
        book_repo.find_by_external_id.return_value = existing
        club_repo.exists_by_club_id_and_catalog_book_id.return_value = True
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        book_repo.fill_missing_fields.assert_not_called()


def describe_link_candidate_scoring():
    async def it_discards_candidates_below_the_similarity_threshold(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
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
        book_repo.find_by_external_id.return_value = None
        link_provider.find_links.return_value = [_candidate(languages=["pt-BR"])]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=["en"]))

        assert captured["book"].urls == {}

    async def it_keeps_a_candidate_with_multiple_languages_when_any_of_them_matches(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        link_provider.find_links.return_value = [_candidate(languages=["pt-BR", "en"])]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=["en"]))

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/hobbit.pdf"

    async def it_prefers_an_exact_language_match_over_a_same_base_language_match_for_the_same_extension(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        base_match = _candidate(languages=["pt-PT"], url="https://mirror.example.com/pt-pt.pdf")
        exact_match = _candidate(languages=["pt-BR"], url="https://mirror.example.com/pt-br.pdf")
        link_provider.find_links.return_value = [base_match, exact_match]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=["pt-BR"]))

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/pt-br.pdf"

    async def it_does_not_filter_by_language_when_no_preferred_languages_are_given(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        link_provider.find_links.return_value = [_candidate(languages=["pt-BR"])]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(languages=[]))

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/hobbit.pdf"

    async def it_redistributes_the_author_weight_when_the_suggestion_has_no_authors(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        link_provider.find_links.return_value = [_candidate(title="The Hobbit (Deluxe)", authors=[])]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion(authors=[]))

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/hobbit.pdf"

    async def it_prefers_a_verified_author_match_over_a_candidate_missing_author_data(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
        no_author_data = _candidate(authors=[], url="https://mirror.example.com/no-author.pdf")
        verified_author = _candidate(url="https://mirror.example.com/verified-author.pdf")
        link_provider.find_links.return_value = [no_author_data, verified_author]

        captured = {}

        async def fake_save(book):
            captured["book"] = book
            book.id = SOME_BOOK_ID
            return book

        book_repo.save.side_effect = fake_save
        service = _service(book_repo, club_repo, link_provider)

        await service.suggest_book_to_club(SOME_CLUB_ID, SOME_USER_ID, _suggestion())

        assert str(captured["book"].urls[ExtensionType.PDF]) == "https://mirror.example.com/verified-author.pdf"

    async def it_ignores_a_link_provider_that_raises(
        book_repo: AsyncMock, club_repo: AsyncMock, link_provider: AsyncMock
    ):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.is_suggestions_allowed.return_value = True
        book_repo.find_by_external_id.return_value = None
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
        book_repo.find_by_external_id.return_value = None
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
