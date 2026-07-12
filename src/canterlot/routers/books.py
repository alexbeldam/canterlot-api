from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.dto.book import BookDetails, BookResponse
from canterlot.exceptions import (
    BookDetailsNotFoundError,
    BookNotFoundError,
    InvalidCredentialsError,
    TokenExpiredError,
)
from canterlot.exceptions.auth import TokenMalformedError
from canterlot.models import ErrorResponseModel
from canterlot.models.book import BookExternalId
from canterlot.routers.dependencies import (
    get_book_id_from_identifier,
    get_book_service,
    get_current_user_id,
    get_user_service,
)
from canterlot.routers.openapi import INTERNAL_SERVER_ERROR_EXAMPLE, error_example
from canterlot.services import BookService, UserService
from canterlot.utils.format import ISBNStr

router = APIRouter(prefix="/books", tags=["Books"])


@router.get(
    "/external/{identifier}",
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
    },
)
async def get_external_book_details(
    identifier: BookExternalId,
    search_service: Annotated[BookService, Depends(get_book_service)],
):
    return await search_service.get_external_book_details(identifier.book_id, identifier.provider)


@router.get(
    "/{identifier}",
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


@router.post(
    "/{identifier}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Book successfully recorded in the user's reading history."},
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponseModel,
            "description": (
                "BookNotFoundError: No book matches the given identifier, whether it was an ISBN-10, "
                "an ISBN-13, or a provider external ID."
            ),
            "content": error_example(BookNotFoundError),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error. The identifier is invalid."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity failure.",
            "content": INTERNAL_SERVER_ERROR_EXAMPLE,
        },
    },
)
async def mark_read(
    book_id: Annotated[PydanticObjectId, Depends(get_book_id_from_identifier)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    await user_service.mark_book_read(user_id=current_user_id, book_id=book_id)
