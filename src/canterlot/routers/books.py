from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query, status

from canterlot.models import BookDetails, BookModel, ErrorResponseModel, PaginatedBooksResponse
from canterlot.models.book import TitleStr
from canterlot.models.enums import BookProviderName
from canterlot.routers.dependencies import get_book_service
from canterlot.services import BookService
from canterlot.utils.format import ISBNStr, LanguageStr

router = APIRouter(prefix="/books", tags=["Books"])


@router.get(
    "/external",
    response_model=PaginatedBooksResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Successfully retrieved paginated list of external books matching criteria."
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. Provided query parameters (page/limit) violate constraints."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected backend error, cache layer failure, or upstream timeout.",
        },
    },
)
async def search_books(
    title: TitleStr,
    search_service: Annotated[BookService, Depends(get_book_service)],
    preferred_languages: Annotated[list[LanguageStr], Query(default_factory=list)],
    author: str | None = None,
    isbn: ISBNStr | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=5, ge=1, le=40),
):
    return await search_service.search_external_books(
        title=title,
        author=author,
        isbn=isbn,
        preferred_languages=preferred_languages,
        page=page,
        limit=limit,
    )


@router.get(
    "/external/{provider_book_id}",
    response_model=BookDetails,
    responses={
        status.HTTP_200_OK: {"description": "Successfully retrieved specific external book details."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "BookDetailsNotFoundError: The active provider engine "
                "was not found, or the volume does not exist on that provider."
            ),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The provider query parameter is not a recognized provider name."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected global or integration breakdown.",
        },
    },
)
async def get_external_book_details(
    provider_book_id: str,
    provider: BookProviderName,
    search_service: Annotated[BookService, Depends(get_book_service)],
):
    return await search_service.get_external_book_details(provider_book_id, provider)


@router.get(
    "/{book_id}",
    response_model=BookModel,
    responses={
        status.HTTP_200_OK: {"description": "Successfully retrieved internal book record."},
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": "BookNotFoundError: The specified book identifier does not exist in the system.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The book_id path parameter is not a valid object identifier."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Internal server/database connection failure.",
        },
    },
)
async def get_book(
    book_id: PydanticObjectId,
    book_service: Annotated[BookService, Depends(get_book_service)],
):
    return await book_service.get_by_id(book_id)
