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
from canterlot.routers.responses import (
    GET_CLUB_CATALOG_RESPONSES,
    REMOVE_FROM_CLUB_RESPONSES,
    SUGGEST_BOOK_RESPONSES,
)
from canterlot.services import CatalogService
from canterlot.types import ClubSlugStr

from .dependencies.providers import (
    get_book_id_from_identifier,
    get_catalog_service,
    get_club_id_from_slug,
    get_current_user_id,
)

router = APIRouter(prefix="/clubs/{club_slug}/catalog", tags=["Club Catalogs"])


@router.post(
    "",
    operation_id="suggestBookToClub",
    response_model=SuggestionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=SUGGEST_BOOK_RESPONSES,
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
    responses=GET_CLUB_CATALOG_RESPONSES,
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
        q=filters.q,
    )


@router.delete(
    "/{identifier}",
    operation_id="removeFromClub",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=REMOVE_FROM_CLUB_RESPONSES,
)
async def remove_from_club(
    book_id: Annotated[PydanticObjectId, Depends(get_book_id_from_identifier)],
    club_id: Annotated[PydanticObjectId, Depends(get_club_id_from_slug)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
):
    await catalog_service.remove_book_from_club(club_id, book_id, current_user_id)
