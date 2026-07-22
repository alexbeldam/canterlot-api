from typing import Annotated

import resend
from fastapi import APIRouter, Depends, Header, Request, status

from canterlot.emails.webhooks import ResendWebhookHandler
from canterlot.exceptions.gateway import InvalidWebhookSignatureError
from canterlot.gateways.auth.risc import GoogleRiscVerifier, RiscVerificationError
from canterlot.types import AuthProviderName
from canterlot.use_cases import RevokeAuthProviderUseCase

from .dependencies.providers import (
    get_google_risc_verifier,
    get_resend_webhook_handler,
    get_revoke_auth_provider_use_case,
)

webhooks_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

GOOGLE_RISC_TOKENS_REVOKED_EVENT = "https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked"


@webhooks_router.post("/google/risc", status_code=status.HTTP_202_ACCEPTED)
async def receive_google_risc_event(
    request: Request,
    verifier: Annotated[GoogleRiscVerifier, Depends(get_google_risc_verifier)],
    use_case: Annotated[RevokeAuthProviderUseCase, Depends(get_revoke_auth_provider_use_case)],
) -> None:
    body = await request.body()

    try:
        claims = await verifier.verify(body.decode())
    except RiscVerificationError:
        raise InvalidWebhookSignatureError("Invalid or untrusted Google RISC token.") from None

    events = claims.get("events", {})
    if GOOGLE_RISC_TOKENS_REVOKED_EVENT in events:
        external_id = claims.get("subject", {}).get("sub")
        if external_id:
            await use_case.execute(
                provider=AuthProviderName.GOOGLE,
                external_id=external_id,
            )


@webhooks_router.post("/resend/events", status_code=status.HTTP_200_OK)
async def receive_resend_event(
    request: Request,
    svix_id: Annotated[str, Header(alias="svix-id")],
    svix_timestamp: Annotated[str, Header(alias="svix-timestamp")],
    svix_signature: Annotated[str, Header(alias="svix-signature")],
    webhook_handler: Annotated[ResendWebhookHandler, Depends(get_resend_webhook_handler)],
) -> None:
    if not all([svix_id, svix_timestamp, svix_signature]):
        raise InvalidWebhookSignatureError("Missing required Svix headers")

    body = await request.body()
    payload = body.decode("utf-8")

    await webhook_handler.handle_webhook(
        payload=payload,
        headers=resend.WebhookHeaders(
            id=svix_id,
            timestamp=svix_timestamp,
            signature=svix_signature,
        ),
    )
