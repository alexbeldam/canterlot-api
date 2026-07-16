from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from canterlot.routers.dependencies import get_health_service
from canterlot.services import HealthService

health_router = APIRouter(tags=["Health"])


@health_router.get("/health", status_code=status.HTTP_200_OK, include_in_schema=False)
async def check_health(health_service: Annotated[HealthService, Depends(get_health_service)]) -> None:
    if not await health_service.check():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
