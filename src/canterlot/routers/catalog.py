from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.catalog import (
    BookSuggestionRequest,
    CatalogFilters,
    PaginatedCatalogResponse,
    SuggestionResponse,
    SuggestionStatus,
)
from canterlot.exceptions import (
    BookNotFoundError,
    ClubNotFoundError,
    ClubSuggestionsClosedError,
    InvalidCredentialsError,
    TokenExpiredError,
    UnauthorizedClubMemberError,
)
from canterlot.exceptions.auth import TokenMalformedError
from canterlot.models import ErrorResponseModel
from canterlot.models.club import ClubSlugStr
from canterlot.routers.dependencies import (
    get_book_id_from_identifier,
    get_catalog_service,
    get_club_id_from_slug,
    get_current_user_id,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import CatalogService

router = APIRouter(prefix="/clubs/{club_slug}/catalog", tags=["Club Catalogs"])


@router.post(
    "",
    operation_id="suggestBookToClub",
    response_model=SuggestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {"description": "Book suggestion newly added to the club catalog."},
        status.HTTP_200_OK: {
            "description": "This book already exists in the club's catalog; the existing entry is returned."
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
    club_slug: ClubSlugStr,
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    suggestion: BookSuggestionRequest,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    response: Response,
) -> SuggestionResponse:
    result = await catalog_service.suggest_book_to_club(
        club_id=club_id,
        user_id=current_user_id,
        suggestion=suggestion,
    )

    if result.status == SuggestionStatus.ALREADY_EXISTS:
        response.status_code = status.HTTP_200_OK
    else:
        response.headers["Location"] = f"/v1/clubs/{club_slug}/catalog/{result.book_external_id}"

    return result


@router.get(
    "",
    operation_id="getClubCatalog",
    response_model=PaginatedCatalogResponse,
    responses={
        status.HTTP_200_OK: {"description": "Successfully retrieved a paginated page of the club's catalog."},
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
            "description": "Validation error. The club_slug path parameter or query parameters are invalid."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def get_club_catalog(
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    filters: Annotated[CatalogFilters, Depends()],
):
    return await catalog_service.get_catalog_page(
        club_id=club_id,
        current_user_id=current_user_id,
        page=filters.page,
        limit=filters.limit,
        sort_by=filters.sort_by,
        sort_direction=filters.sort_direction,
        suggested_by=filters.suggested_by,
    )


@router.delete(
    "/{identifier}",
    operation_id="removeFromClub",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Book successfully removed from the club catalog."},
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
                "UnauthorizedClubMemberError: The requesting user is neither an OWNER/ADMIN "
                "nor the member who originally suggested this book."
            ),
            "content": error_example(UnauthorizedClubMemberError),
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "ClubNotFoundError, or BookNotFoundError: the club or the book identifier doesn't resolve, "
                "or the book isn't in this club's catalog."
            ),
            "content": error_example(ClubNotFoundError, BookNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_slug or identifier path parameter is invalid."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def remove_from_club(
    book_id: Annotated[PydanticObjectId, Depends(get_book_id_from_identifier)],
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
):
    await catalog_service.remove_book_from_club(club_id, book_id, current_user_id)
