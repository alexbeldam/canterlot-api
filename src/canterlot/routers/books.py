from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.models import BookDetails, BookModel, ErrorResponseModel
from canterlot.models.enums import BookProviderName
from canterlot.routers.dependencies import get_book_service
from canterlot.services import BookService

router = APIRouter(prefix="/books", tags=["Books"])


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
