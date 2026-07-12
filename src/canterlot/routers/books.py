from dataclasses import dataclass
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query, status

from canterlot.dto.book import BookDetails, BookResponse, PaginatedBooksResponse
from canterlot.exceptions import (
    BookDetailsNotFoundError,
    BookNotFoundError,
    BookProviderUnavailableError,
    BookSearchCriteriaMissingError,
    ClubNotFoundError,
    InvalidCredentialsError,
    TokenExpiredError,
    UnauthorizedClubMemberError,
)
from canterlot.models import ErrorResponseModel
from canterlot.models.book import BookExternalId, TitleStr
from canterlot.routers.dependencies import (
    get_book_service,
    get_club_id_from_slug,
    get_club_service,
    get_current_user_id,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import BookService, ClubService
from canterlot.utils.format import ISBNStr

router = APIRouter(prefix="/books", tags=["Books"])


@dataclass
class ExternalBookSearchFilters:
    title: TitleStr | None = None
    author: str | None = None
    isbn: ISBNStr | None = None
    page: int = Query(default=1, ge=1)
    limit: int = Query(default=5, ge=1, le=40)


@router.get(
    "/external/{identifier}",
    operation_id="getExternalBookDetails",
    response_model=BookDetails,
    responses={
        status.HTTP_200_OK: {"description": "Successfully retrieved specific external book details."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "BookDetailsNotFoundError: The active provider engine "
                "was not found, or the volume does not exist on that provider."
            ),
            "content": error_example(BookDetailsNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Validation error. The identifier does not follow the 'provider__id' format, "
                "or its provider segment is not a recognized provider name."
            )
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected global or integration breakdown.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponseModel,
            "description": (
                "BookProviderUnavailableError: The external provider responded with an unexpected error "
                "(rate limit, quota, or an outage) rather than confirming the volume doesn't exist."
            ),
            "content": error_example(BookProviderUnavailableError),
        },
    },
)
async def get_external_book_details(
    identifier: BookExternalId,
    search_service: Annotated[BookService, Depends(get_book_service)],
):
    return await search_service.get_external_book_details(identifier.book_id, identifier.provider)


@router.get(
    "/external",
    operation_id="searchExternalBooks",
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
            "description": "UnauthorizedClubMemberError: The requesting user is not a member of club_slug.",
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "ClubNotFoundError: No club exists with the given club_slug.",
            "content": error_example(ClubNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error. The query parameters are invalid."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected backend error, cache layer failure, or upstream timeout.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def search_external_books(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
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


@router.get(
    "/{identifier}",
    operation_id="getBook",
    response_model=BookResponse,
    responses={
        status.HTTP_200_OK: {"description": "Successfully retrieved internal book record."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "BookNotFoundError: No book matches the given identifier, whether it was an ISBN-10, "
                "an ISBN-13, or a provider external ID."
            ),
            "content": error_example(BookNotFoundError),
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Internal server/database connection failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_book(
    identifier: BookExternalId | ISBNStr,
    book_service: Annotated[BookService, Depends(get_book_service)],
):
    return await book_service.get_by_identifier(identifier)
