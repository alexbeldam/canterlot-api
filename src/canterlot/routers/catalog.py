from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, status

from canterlot.models import BookSuggestionRequest, ErrorResponseModel, SuggestionResponse
from canterlot.routers.dependencies import get_catalog_service, get_current_user_id
from canterlot.services import CatalogService

router = APIRouter(prefix="/clubs/{club_id}/catalog", tags=["Club Catalogs"])


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
        },
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponseModel,
            "description": (
                "InvalidCredentialsError or TokenExpiredError: The bearer token is missing, invalid, or expired."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponseModel,
            "description": (
                "UnauthorizedClubMemberError or ClubSuggestionsClosedError: The requesting user is either "
                "not a member of this club or suggestions are currently closed."
            ),
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error. The club_id path parameter or suggestion payload is invalid."
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponseModel,
            "description": "Unexpected database connectivity or link provider scraping failure.",
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
