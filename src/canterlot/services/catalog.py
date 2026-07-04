import asyncio

import langcodes
from beanie import PydanticObjectId

from canterlot.exceptions import ClubSuggestionsClosedError, UnauthorizedClubMemberError
from canterlot.models import BookModel, BookSuggestionRequest, LinkCandidate, SuggestionResponse, SuggestionStatus
from canterlot.models.book import SearchParams, TitleStr, UrlList
from canterlot.models.club import CatalogEntryModel
from canterlot.models.enums import ExtensionType
from canterlot.providers import LinkProvider
from canterlot.repositories import BookRepository, ClubRepository
from canterlot.utils import get_logger, similarity_ratio
from canterlot.utils.format import LanguageStr, NonEmptyStr

logger = get_logger(__name__)

type UrlScores = dict[ExtensionType, float]


class CatalogService:
    THRESHOLD = 0.65

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
            provider=suggestion.provider,
            source_id=suggestion.source_id,
            book_title=suggestion.title,
        )
        log.info("Processing book suggestion request for club catalog")

        if not await self.__club_repo.exists_by_club_id_and_member_user_id(club_id, user_id):
            log.warn("Suggestion rejected: user is not a member of the club")
            raise UnauthorizedClubMemberError("Only members of this club can suggest books.")

        if not await self.__club_repo.is_suggestions_allowed(club_id):
            log.warn("Suggestion rejected: club suggestions queue is closed")
            raise ClubSuggestionsClosedError("Suggestions are currently closed for this club.")

        book = await self.__book_repo.find_by_provider_and_provider_book_id(suggestion.provider, suggestion.source_id)

        if book and book.id:
            book_id = PydanticObjectId(book.id)
            log = log.bind(book_id=str(book_id))

            missing_extensions = [ext for ext in ExtensionType if ext not in book.urls]

            if missing_extensions:
                log.info(
                    "Book found but missing formats, initiating targeted scraping sequence", formats=missing_extensions
                )
                links = await self.__scrape_best_links(suggestion, missing_extensions)

                if links:
                    await self.__book_repo.add_to_urls(book.id, links)

                    log.info(
                        "Successfully supplemented database reference with discovered formats",
                        formats=list(links.keys()),
                    )

            already_linked = await self.__club_repo.exists_by_club_id_and_catalog_book_id(club_id, book_id)
            if already_linked:
                log.info(
                    "Suggestion processed: book already exists in club catalog",
                    status=SuggestionStatus.ALREADY_EXISTS,
                )
                return SuggestionResponse(status=SuggestionStatus.ALREADY_EXISTS, book_id=book.id)
        else:
            log.info("Book not found in global database, initiating scraping sequence")
            links = await self.__scrape_best_links(suggestion, list(ExtensionType))
            book_data = suggestion.model_dump(exclude={"source_id"})

            new_book = BookModel(provider_book_id=suggestion.source_id, urls=links, **book_data)

            book = await self.__book_repo.save(new_book)
            book_id = PydanticObjectId(book.id)
            log = log.bind(book_id=str(book_id))
            log.info("Successfully scraped and persisted new global book reference")

        entry = CatalogEntryModel(
            book_id=book_id,
            suggested_by=user_id,
        )

        await self.__club_repo.add_to_catalog(club_id=club_id, entry=entry)

        log.info("Book suggestion transaction completed successfully", status=SuggestionStatus.SUCCESS)
        return SuggestionResponse(status=SuggestionStatus.SUCCESS, book_id=book_id)

    def __matches_preferred_language(self, candidate: LinkCandidate, languages: list[LanguageStr]) -> bool:
        if not languages or not candidate.language:
            return True

        try:
            candidate_base = langcodes.get(candidate.language).language
            return any(langcodes.get(target_lang).language == candidate_base for target_lang in languages)
        except (LookupError, ValueError):
            return any(lang == candidate.language for lang in languages)

    def __score_candidate(
        self,
        candidate: LinkCandidate,
        target_title: TitleStr,
        target_authors: list[NonEmptyStr],
    ) -> float:
        title_score = similarity_ratio(target_title, candidate.title)
        author_score = max(
            (
                similarity_ratio(target, candidate_author)
                for target in target_authors
                for candidate_author in candidate.authors
            ),
            default=0,
        )
        return (title_score * 0.6) + (author_score * 0.4)

    def __evaluate_candidates_with_scores(
        self,
        candidates: list[LinkCandidate],
        target_title: TitleStr,
        target_authors: list[NonEmptyStr],
        languages: list[LanguageStr],
        current_scores: UrlScores,
    ) -> tuple[UrlList, UrlScores]:
        discovered_urls: UrlList = {}

        for candidate in candidates:
            if not self.__matches_preferred_language(candidate, languages):
                continue

            ext = candidate.extension
            combined_score = self.__score_candidate(candidate, target_title, target_authors)

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
