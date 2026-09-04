from dataclasses import dataclass
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query

from canterlot.dto.book import BookDetails, BookResponse, PaginatedBooksResponse
from canterlot.models.book import BookModel
from canterlot.routers.responses import (
    GET_BOOK_RESPONSES,
    GET_EXTERNAL_BOOK_DETAILS_RESPONSES,
    SEARCH_EXTERNAL_BOOKS_RESPONSES,
)
from canterlot.services import BookService, ClubService
from canterlot.types import BookExternalId, ISBNStr, TitleStr

from .dependencies.providers import (
    get_book_from_identifier,
    get_book_service,
    get_club_id_from_slug,
    get_club_service,
    get_current_user_id,
)

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
    responses=GET_EXTERNAL_BOOK_DETAILS_RESPONSES,
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
    responses=SEARCH_EXTERNAL_BOOKS_RESPONSES,
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
    responses=GET_BOOK_RESPONSES,
)
async def get_book(book: Annotated[BookModel, Depends(get_book_from_identifier)]):
    return BookResponse.model_validate(book, from_attributes=True)
