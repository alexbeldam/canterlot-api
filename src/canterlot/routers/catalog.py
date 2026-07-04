from dataclasses import dataclass
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query, status

from canterlot.exceptions import (
    BookSearchCriteriaMissingError,
    ClubSuggestionsClosedError,
    InvalidCredentialsError,
    TokenExpiredError,
    UnauthorizedClubMemberError,
)
from canterlot.exceptions.auth import TokenMalformedError
from canterlot.models import BookSuggestionRequest, ErrorResponseModel, PaginatedBooksResponse, SuggestionResponse
from canterlot.models.book import TitleStr
from canterlot.routers.dependencies import get_book_service, get_catalog_service, get_club_service, get_current_user_id
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import BookService, CatalogService, ClubService
from canterlot.utils.format import ISBNStr

router = APIRouter(prefix="/clubs/{club_id}/catalog", tags=["Club Catalogs"])


@dataclass
class ExternalBookSearchFilters:
    title: TitleStr | None = None
    author: str | None = None
    isbn: ISBNStr | None = None
    page: int = Query(default=1, ge=1)
    limit: int = Query(default=5, ge=1, le=40)


@router.post(
    "/",
    response_model=SuggestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "Book suggestion successfully added to the club catalog or identified as already existing."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "TokenMalformedError: The bearer token is corrupt, malformed, or altered.",
            "content": error_example(TokenMalformedError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired."
            ),
            "content": error_example(InvalidCredentialsError, TokenExpiredError),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": (
                "UnauthorizedClubMemberError or ClubSuggestionsClosedError: The requesting user is either "
                "not a member of this club or suggestions are currently closed."
            ),
            "content": error_example(UnauthorizedClubMemberError, ClubSuggestionsClosedError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_id path parameter or suggestion payload is invalid."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity or link provider scraping failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def suggest_book_to_club(
    club_id: PydanticObjectId,
    suggestion: BookSuggestionRequest,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
):
    return await catalog_service.suggest_book_to_club(
        club_id=club_id,
        user_id=current_user_id,
        suggestion=suggestion,
    )


@router.get(
    "/search/external",
    response_model=PaginatedBooksResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Successfully retrieved paginated list of external books matching criteria."
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponseModel,
            "description": "BookSearchCriteriaMissingError: None of title, author, or isbn were provided.",
            "content": error_example(BookSearchCriteriaMissingError),
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired."
            ),
            "content": error_example(InvalidCredentialsError, TokenExpiredError),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": "UnauthorizedClubMemberError: The requesting user is not a member of this club.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_id path parameter or query parameters are invalid."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected backend error, cache layer failure, or upstream timeout.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def search_external_books_for_club(
    club_id: PydanticObjectId,
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    club_service: Annotated[ClubService, Depends(get_club_service)],
    search_service: Annotated[BookService, Depends(get_book_service)],
    filters: Annotated[ExternalBookSearchFilters, Depends()],
):
    preferred_languages = await club_service.get_preferred_languages(club_id, current_user_id)
    return await search_service.search_external_books(
        title=filters.title,
        author=filters.author,
        isbn=filters.isbn,
        preferred_languages=preferred_languages,
        page=filters.page,
        limit=filters.limit,
    )
