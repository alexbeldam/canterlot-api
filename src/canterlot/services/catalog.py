import asyncio

from beanie import PydanticObjectId

from canterlot.dto.catalog import BookSuggestionRequest, SuggestionResponse, SuggestionStatus
from canterlot.exceptions import BookNotFoundError, ClubSuggestionsClosedError, UnauthorizedClubMemberError
from canterlot.models import BookModel, LinkCandidate
from canterlot.models.book import AuthorList, SearchParams, TitleStr, UrlList
from canterlot.models.club import CatalogEntryModel
from canterlot.models.enums import ExtensionType, MemberRole
from canterlot.providers import LinkProvider
from canterlot.repositories import BookRepository, ClubRepository
from canterlot.utils import (
    LANGUAGE_MATCH_SUBSCORES,
    LanguageMatchLevel,
    best_language_match,
    get_logger,
    redistribute_weights,
    similarity_ratio,
)
from canterlot.utils.format import LanguageStr

logger = get_logger(__name__)

type UrlScores = dict[ExtensionType, float]


class CatalogService:
    THRESHOLD = 0.65
    TITLE_WEIGHT = 0.5
    AUTHOR_WEIGHT = 0.3
    LANGUAGE_WEIGHT = 0.2
    FILLABLE_SCALAR_FIELDS = ("year", "page_count", "isbn_10", "isbn_13", "description", "cover_url")
    FILLABLE_LIST_FIELDS = ("authors", "categories", "languages")

    def __init__(
        self,
        book_repo: BookRepository,
        club_repo: ClubRepository,
        link_providers: list[LinkProvider],
    ):
        self.__book_repo = book_repo
        self.__club_repo = club_repo
        self.__link_providers = link_providers

    async def suggest_book_to_club(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
        suggestion: BookSuggestionRequest,
    ) -> SuggestionResponse:
        log = logger.bind(
            club_id=str(club_id),
            user_id=str(user_id),
            source_id=suggestion.source_id,
            book_title=suggestion.title,
        )
        log.info("Processing book suggestion request for club catalog")

        await self.__ensure_suggestion_allowed(club_id, user_id, log)

        book = await self.__find_existing_book(suggestion)

        if book and book.id:
            book_id = PydanticObjectId(book.id)
            external_id = book.external_id
            log = log.bind(book_id=str(book_id))

            await self.__supplement_existing_book(book, book_id, suggestion, log)

            if await self.__club_repo.exists_by_club_id_and_catalog_book_id(club_id, book_id):
                log.info(
                    "Suggestion processed: book already exists in club catalog",
                    status=SuggestionStatus.ALREADY_EXISTS,
                )
                return SuggestionResponse(status=SuggestionStatus.ALREADY_EXISTS, book_external_id=external_id)
        else:
            book_id = await self.__create_new_book(suggestion, log)
            external_id = suggestion.source_id
            log = log.bind(book_id=str(book_id))

        entry = CatalogEntryModel(
            book_id=book_id,
            suggested_by=user_id,
        )

        await self.__club_repo.add_to_catalog(club_id=club_id, entry=entry)

        log.info("Book suggestion transaction completed successfully", status=SuggestionStatus.SUCCESS)
        return SuggestionResponse(status=SuggestionStatus.SUCCESS, book_external_id=external_id)

    async def remove_book_from_club(
        self,
        club_id: PydanticObjectId,
        book_id: PydanticObjectId,
        current_user_id: PydanticObjectId,
    ) -> None:
        log = logger.bind(club_id=str(club_id), book_id=str(book_id), current_user_id=str(current_user_id))
        log.info("Attempting to remove a book from the club catalog")

        entry = await self.__club_repo.find_catalog_entry_by_club_id_and_book_id(club_id, book_id)
        if entry is None:
            log.warn("Removal rejected: book is not in this club's catalog")
            raise BookNotFoundError(f"Book with ID '{book_id}' not found in this club's catalog")

        role = await self.__club_repo.find_member_role_by_club_id_and_user_id(club_id, current_user_id)
        is_privileged = role in (MemberRole.ADMIN, MemberRole.OWNER)
        is_original_suggester = entry.suggested_by == current_user_id

        if not is_privileged and not is_original_suggester:
            log.warn("Removal rejected: caller is neither privileged nor the original suggester")
            raise UnauthorizedClubMemberError(
                "Only an OWNER, ADMIN, or the original suggester can remove a book from the catalog."
            )

        await self.__club_repo.remove_from_catalog(club_id, book_id)
        log.info("Book removed from club catalog successfully")

    async def __ensure_suggestion_allowed(self, club_id: PydanticObjectId, user_id: PydanticObjectId, log) -> None:
        if not await self.__club_repo.exists_by_club_id_and_member_user_id(club_id, user_id):
            log.warn("Suggestion rejected: user is not a member of the club")
            raise UnauthorizedClubMemberError("Only members of this club can suggest books.")

        if not await self.__club_repo.is_suggestions_allowed(club_id):
            log.warn("Suggestion rejected: club suggestions queue is closed")
            raise ClubSuggestionsClosedError("Suggestions are currently closed for this club.")

    async def __find_existing_book(self, suggestion: BookSuggestionRequest) -> BookModel | None:
        book = None
        if suggestion.isbn_10 or suggestion.isbn_13:
            book = await self.__book_repo.find_by_isbn(suggestion.isbn_10, suggestion.isbn_13)

        if book is None:
            book = await self.__book_repo.find_by_external_id(suggestion.source_id)

        return book

    async def __supplement_existing_book(
        self,
        book: BookModel,
        book_id: PydanticObjectId,
        suggestion: BookSuggestionRequest,
        log,
    ) -> None:
        missing_extensions = [ext for ext in ExtensionType if ext not in book.urls]

        if missing_extensions:
            log.info(
                "Book found but missing formats, initiating targeted scraping sequence", formats=missing_extensions
            )
            links = await self.__scrape_best_links(suggestion, missing_extensions)

            if links:
                await self.__book_repo.add_to_urls(book_id, links)

                log.info(
                    "Successfully supplemented database reference with discovered formats",
                    formats=list(links.keys()),
                )

        missing_fields = self.__resolve_missing_fields(book, suggestion)
        if missing_fields:
            await self.__book_repo.fill_missing_fields(book_id, missing_fields)
            log.info(
                "Supplemented existing book with previously missing metadata",
                fields=list(missing_fields.keys()),
            )

    async def __create_new_book(self, suggestion: BookSuggestionRequest, log) -> PydanticObjectId:
        log.info("Book not found in global database, initiating scraping sequence")
        links = await self.__scrape_best_links(suggestion, list(ExtensionType))
        book_data = suggestion.model_dump(exclude={"source_id"})

        new_book = BookModel(external_id=suggestion.source_id, urls=links, **book_data)

        book = await self.__book_repo.save(new_book)
        book_id = PydanticObjectId(book.id)
        log.bind(book_id=str(book_id)).info("Successfully scraped and persisted new global book reference")

        return book_id

    def __resolve_missing_fields(self, book: BookModel, suggestion: BookSuggestionRequest) -> dict[str, object]:
        updates: dict[str, object] = {}

        for field in self.FILLABLE_SCALAR_FIELDS:
            if getattr(book, field) is None:
                value = getattr(suggestion, field)
                if value is not None:
                    updates[field] = value

        for field in self.FILLABLE_LIST_FIELDS:
            if not getattr(book, field):
                value = getattr(suggestion, field)
                if value:
                    updates[field] = value

        return updates

    def __resolve_language_match(self, candidate: LinkCandidate, languages: list[LanguageStr]) -> LanguageMatchLevel:
        if not languages or not candidate.languages:
            return LanguageMatchLevel.NONE

        return best_language_match(candidate.languages, languages)

    def __score_candidate(
        self,
        candidate: LinkCandidate,
        target_title: TitleStr,
        target_authors: AuthorList,
        languages: list[LanguageStr],
        language_match: LanguageMatchLevel,
    ) -> float:
        title_score = similarity_ratio(target_title, candidate.title)
        weights = {"title": self.TITLE_WEIGHT}

        author_score = 0.0
        if target_authors:
            author_score = max(
                (
                    similarity_ratio(target, candidate_author)
                    for target in target_authors
                    for candidate_author in candidate.authors
                ),
                default=0,
            )
            weights["author"] = self.AUTHOR_WEIGHT

        language_score = 0.0
        if languages:
            language_score = LANGUAGE_MATCH_SUBSCORES[language_match]
            weights["language"] = self.LANGUAGE_WEIGHT

        weights = redistribute_weights(weights)

        return (
            title_score * weights["title"]
            + author_score * weights.get("author", 0)
            + language_score * weights.get("language", 0)
        )

    def __evaluate_candidates_with_scores(
        self,
        candidates: list[LinkCandidate],
        target_title: TitleStr,
        target_authors: AuthorList,
        languages: list[LanguageStr],
        current_scores: UrlScores,
    ) -> tuple[UrlList, UrlScores]:
        discovered_urls: UrlList = {}

        for candidate in candidates:
            language_match = self.__resolve_language_match(candidate, languages)

            if languages and candidate.languages and language_match is LanguageMatchLevel.NONE:
                continue

            ext = candidate.extension
            combined_score = self.__score_candidate(candidate, target_title, target_authors, languages, language_match)

            if combined_score > current_scores.get(ext, self.THRESHOLD):
                discovered_urls[ext] = candidate.url
                current_scores[ext] = combined_score
                logger.debug(
                    f"New best {ext.value.upper()} candidate discovered",
                    score=round(combined_score, 4),
                    title=candidate.title,
                )

        return discovered_urls, current_scores

    async def __scrape_best_links(
        self,
        suggestion: BookSuggestionRequest,
        target_extensions: list[ExtensionType],
    ) -> UrlList:
        logger.info(
            "Triggering concurrent provider search tasks",
            providers_count=len(self.__link_providers),
            title=suggestion.title,
            authors=suggestion.authors,
            target_extensions=target_extensions,
        )

        params = SearchParams(
            title=suggestion.title,
            authors=suggestion.authors,
            isbn_10=suggestion.isbn_10,
            isbn_13=suggestion.isbn_13,
            languages=suggestion.languages,
            extensions=target_extensions,
        )

        tasks = [provider.find_links(params) for provider in self.__link_providers]

        provider_results = await asyncio.gather(*tasks, return_exceptions=True)

        final_urls: UrlList = {}
        best_scores: UrlScores = {ext: self.THRESHOLD for ext in target_extensions}

        for provider, provider_data in zip(self.__link_providers, provider_results, strict=True):
            if isinstance(provider_data, Exception):
                logger.error(
                    "Link provider task failed during execution",
                    provider_name=provider.name,
                    error_message=str(provider_data),
                    exc_info=True,
                )
                continue

            if not isinstance(provider_data, list):
                continue

            logger.debug(
                "Processing candidates payload from provider",
                provider_name=provider.name,
                items_count=len(provider_data),
            )

            discovered_urls, updated_scores = self.__evaluate_candidates_with_scores(
                candidates=provider_data,
                target_title=suggestion.title,
                target_authors=suggestion.authors,
                languages=suggestion.languages,
                current_scores=best_scores,
            )

            final_urls.update(discovered_urls)
            best_scores = updated_scores

        logger.info(
            "Scraping analysis phase completed",
            urls_found=list(final_urls.keys()),
        )

        return final_urls
