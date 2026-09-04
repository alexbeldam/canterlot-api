import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeGuard

import resend

from canterlot.constants import (
    EMAIL_PREFERENCES_KEY_TEMPLATE,
    EXTERNAL_SUPPRESSION_TEMPLATE,
    RESEND_WEBHOOK_KEY_TEMPLATE,
)
from canterlot.exceptions.gateway import InvalidWebhookSignatureError
from canterlot.repositories.interfaces import CacheRepository, UserRepository
from canterlot.types import NormalizedEmailStr
from canterlot.utils import get_logger

logger = get_logger(__name__)


class EventType(StrEnum):
    BOUNCED = "email.bounced"
    SUPPRESSED = "email.suppressed"
    COMPLAINED = "email.complained"
    FAILED = "email.failed"
    DELIVERED = "email.delivered"


SupportedEmailEvent = (
    resend.EmailBouncedEvent
    | resend.EmailSuppressedEvent
    | resend.EmailComplainedEvent
    | resend.EmailFailedEvent
    | resend.EmailDeliveredEvent
)


def is_supported_email_event(event: Any) -> TypeGuard[SupportedEmailEvent]:
    return isinstance(event, dict) and event.get("type") in list(EventType)


class ResendWebhookHandler:
    def __init__(
        self,
        cache_repo: CacheRepository,
        user_repo: UserRepository,
        resend_api_key: str,
        resend_webhook_secret: str,
    ):
        self.__cache_repo = cache_repo
        self.__user_repo = user_repo
        self.__webhook_secret = resend_webhook_secret
        resend.api_key = resend_api_key

    async def handle_webhook(self, payload: str, headers: resend.WebhookHeaders) -> None:
        svix_id = headers.get("id")
        if not svix_id:
            logger.warning("Webhook rejection: Missing Svix ID header.")
            raise InvalidWebhookSignatureError("Missing Svix ID header")

        cache_key = RESEND_WEBHOOK_KEY_TEMPLATE.format(svix_id=svix_id)
        if await self.__cache_repo.find(cache_key):
            return

        options: resend.VerifyWebhookOptions = {
            "payload": payload,
            "headers": headers,
            "webhook_secret": self.__webhook_secret,
        }

        try:
            event = resend.Webhooks.verify(options)
        except ValueError:
            logger.error("Webhook rejection: Invalid cryptographic signature.", extra={"svix_id": svix_id})
            raise InvalidWebhookSignatureError("Invalid cryptographic webhook signature") from None

        if not is_supported_email_event(event):
            event_type = event.get("type", "unknown")
            logger.debug(
                "Webhook rejection: Unsupported event type.",
                extra={"svix_id": svix_id, "event_type": event_type},
            )
            return

        type = EventType(event["type"])
        recipients = event["data"]["to"]

        for recipient in recipients:
            await self._evaluate_reputation_event(type, recipient)

        await self.__cache_repo.save(
            key=cache_key,
            mapping={"event": json.dumps(event)},
            expire_seconds=3600,
        )

    async def _evaluate_reputation_event(self, event_type: EventType, email: NormalizedEmailStr) -> None:
        log = logger.bind(email=email, event_type=event_type)
        now = datetime.now(UTC)

        user_exists = await self.__user_repo.exists_by_email(email)

        if not user_exists:
            # --- EXTERNAL RECIPIENT PIPELINE ---
            if event_type in (EventType.BOUNCED, EventType.SUPPRESSED, EventType.COMPLAINED):
                log.warning("External target triggered permanent failure. Setting infrastructure blacklist.")
                await self.__cache_repo.save(
                    key=EXTERNAL_SUPPRESSION_TEMPLATE.format(email=email),
                    mapping={"suppressed": "1", "reason": event_type},
                    expire_seconds=31536000,  # 1 year
                )
            return

        # --- REGISTERED USER PIPELINE ---
        match event_type:
            case EventType.BOUNCED | EventType.SUPPRESSED:
                log.error("Fatal delivery failure. Registering total account suppression.")
                await self.__user_repo.apply_global_suppression_by_email(email, timestamp=now)
                await self._evict_user_preferences_cache(email)

            case EventType.COMPLAINED:
                log.warning("Spam complaint registered. Suppressing non-transactional categories.")
                await self.__user_repo.apply_spam_suppression_by_email(email, timestamp=now)
                await self._evict_user_preferences_cache(email)

            case EventType.FAILED:
                log.warning("Operational failure detected. Flagging delivery failure.")
                await self.__user_repo.set_delivery_failed_by_email(email, failed=True)
                await self._evict_user_preferences_cache(email)

            case _:
                log.debug("Successful delivery confirmed. Executing self-healing loop check.")
                modified = await self.__user_repo.set_delivery_failed_by_email(email, failed=False)
                if modified:
                    log.debug("Self-healing complete: cleared operational delivery_failed lock.")
                    await self._evict_user_preferences_cache(email)

    async def _evict_user_preferences_cache(self, email: NormalizedEmailStr) -> None:
        await self.__cache_repo.invalidate(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))
