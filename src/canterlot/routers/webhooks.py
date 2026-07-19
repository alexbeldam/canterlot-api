from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from canterlot.gateways.auth.risc import GoogleRiscVerifier, RiscVerificationError
from canterlot.routers.dependencies import get_auth_service, get_google_risc_verifier
from canterlot.services import AuthService
from canterlot.types import AuthProviderName

webhooks_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

GOOGLE_RISC_TOKENS_REVOKED_EVENT = "https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked"


@webhooks_router.post("/google/risc", status_code=status.HTTP_202_ACCEPTED)
async def receive_google_risc_event(
    request: Request,
    verifier: Annotated[GoogleRiscVerifier, Depends(get_google_risc_verifier)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    body = await request.body()

    try:
        claims = await verifier.verify(body.decode())
    except RiscVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc

    events = claims.get("events", {})
    if GOOGLE_RISC_TOKENS_REVOKED_EVENT in events:
        external_id = claims.get("subject", {}).get("sub")
        if external_id:
            await auth_service.revoke_provider_link(AuthProviderName.GOOGLE, external_id)
