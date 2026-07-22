from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, status
from fastapi.responses import RedirectResponse

from canterlot.config import get_settings
from canterlot.exceptions.auth import InvalidUnsubscribePayloadError
from canterlot.routers.dependencies.providers import get_process_unsubscribe_use_case
from canterlot.routers.responses import (
    BROWSER_UNSUBSCRIBE_RESPONSES,
    ONE_CLICK_UNSUBSCRIBE_RESPONSES,
)
from canterlot.use_cases.process_unsubscribe import ProcessUnsubscribeUseCase
from canterlot.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/unsubscribe", tags=["Unsubscribe"])


@router.post(
    "",
    operation_id="oneClickUnsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="RFC 8058 One-Click Unsubscribe Endpoint",
    responses=ONE_CLICK_UNSUBSCRIBE_RESPONSES,
)
async def one_click_unsubscribe(
    token: Annotated[str, Query(...)],
    use_case: Annotated[ProcessUnsubscribeUseCase, Depends(get_process_unsubscribe_use_case)],
    list_unsubscribe: Annotated[
        str | None,
        Form(alias="List-Unsubscribe"),
    ] = None,
) -> None:
    """Handles background POST requests from email user agents (Gmail, Yahoo, Apple Mail).

    RFC 8058 requires the body to be form-encoded containing `List-Unsubscribe=One-Click`.
    """
    if list_unsubscribe != "One-Click":
        raise InvalidUnsubscribePayloadError(
            "RFC 8058 One-Click unsubscribe requests must contain 'List-Unsubscribe=One-Click' in the form body."
        )

    await use_case.execute(token)


@router.get(
    "",
    operation_id="browserUnsubscribe",
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Direct Browser Unsubscribe Link Handler",
    responses=BROWSER_UNSUBSCRIBE_RESPONSES,
)
async def browser_unsubscribe(
    token: Annotated[str, Query(...)],
    use_case: Annotated[ProcessUnsubscribeUseCase, Depends(get_process_unsubscribe_use_case)],
) -> RedirectResponse:
    """Handles direct browser link clicks from email bodies and redirects to the web frontend."""
    scope = await use_case.execute(token)
    frontend_url = get_settings().frontend_url
    redirect_target = f"{frontend_url}/unsubscribed?scope={scope.name.lower()}&status=success"

    return RedirectResponse(
        url=redirect_target,
        status_code=status.HTTP_303_SEE_OTHER,
    )
