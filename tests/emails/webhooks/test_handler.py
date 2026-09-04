from unittest.mock import patch

import pytest

from canterlot.constants import (
    EMAIL_PREFERENCES_KEY_TEMPLATE,
    EXTERNAL_SUPPRESSION_TEMPLATE,
)
from canterlot.emails.webhooks.handler import ResendWebhookHandler
from canterlot.exceptions.gateway import InvalidWebhookSignatureError


@pytest.fixture
def handler(cache_repo, user_repo):
    return ResendWebhookHandler(
        cache_repo=cache_repo,
        user_repo=user_repo,
        resend_api_key="test_api_key",
        resend_webhook_secret="test_secret",
    )


@pytest.fixture
def base_headers():
    return {"id": "svix-123"}


def describe_handle_webhook():

    async def it_raises_error_if_svix_id_header_is_missing(handler):
        with pytest.raises(InvalidWebhookSignatureError, match="Missing Svix ID header"):
            await handler.handle_webhook("{}", {})

    async def it_bails_early_if_webhook_id_already_exists_in_cache(handler, cache_repo, base_headers):
        cache_repo.find.return_value = {"event": "cached_data"}

        with patch("resend.Webhooks.verify") as mock_verify:
            await handler.handle_webhook("{}", base_headers)
            mock_verify.assert_not_called()

    async def it_raises_error_if_cryptographic_signature_is_invalid(handler, base_headers):
        with patch("resend.Webhooks.verify") as mock_verify:
            mock_verify.side_effect = ValueError("Invalid signature")
            with pytest.raises(InvalidWebhookSignatureError, match="Invalid cryptographic webhook signature"):
                await handler.handle_webhook("{}", base_headers)

    def describe_external_recipient_pipeline():

        @pytest.mark.parametrize("event_type", ["email.bounced", "email.suppressed", "email.complained"])
        async def it_blacklists_external_recipients_on_permanent_failures(
            handler,
            cache_repo,
            base_headers,
            event_type,
        ):
            email = "external@ponymail.com"
            event = {"type": event_type, "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            cache_repo.save.assert_any_call(
                key=EXTERNAL_SUPPRESSION_TEMPLATE.format(email=email),
                mapping={"suppressed": "1", "reason": event_type},
                expire_seconds=31536000,
            )

        async def it_ignores_non_failure_tracking_events_for_external_recipients(
            handler,
            cache_repo,
            base_headers,
        ):
            email = "external@ponymail.com"
            event = {"type": "email.delivered", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            assert not any(
                call.kwargs.get("key") == EXTERNAL_SUPPRESSION_TEMPLATE.format(email=email)
                for call in cache_repo.save.call_args_list
            )

    def describe_registered_user_pipeline():

        @pytest.mark.parametrize("event_type", ["email.bounced", "email.suppressed"])
        async def it_applies_global_suppression_on_fatal_user_failures(
            handler,
            cache_repo,
            user_repo,
            base_headers,
            event_type,
        ):
            user_repo.exists_by_email.return_value = True
            email = "user@canterlot.dev"
            event = {"type": event_type, "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            user_repo.apply_global_suppression_by_email.assert_awaited_once()
            cache_repo.invalidate.assert_awaited_once_with(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

        async def it_applies_spam_suppression_on_spam_complaints(
            handler,
            cache_repo,
            user_repo,
            base_headers,
        ):
            user_repo.exists_by_email.return_value = True
            email = "user@canterlot.dev"
            event = {"type": "email.complained", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            user_repo.apply_spam_suppression_by_email.assert_awaited_once()
            cache_repo.invalidate.assert_awaited_once_with(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

        async def it_flags_delivery_failure_on_operational_failures(
            handler,
            cache_repo,
            user_repo,
            base_headers,
        ):
            user_repo.exists_by_email.return_value = True
            email = "user@canterlot.dev"
            event = {"type": "email.failed", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            user_repo.set_delivery_failed_by_email.assert_awaited_once_with(email, failed=True)
            cache_repo.invalidate.assert_awaited_once_with(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

        async def it_does_nothing_on_successful_delivery_if_not_previously_locked(
            handler,
            cache_repo,
            user_repo,
            base_headers,
        ):
            user_repo.exists_by_email.return_value = True
            user_repo.set_delivery_failed_by_email.return_value = False
            email = "user@canterlot.dev"
            event = {"type": "email.delivered", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            cache_repo.invalidate.assert_not_awaited()

        async def it_clears_operational_lock_on_successful_delivery_if_previously_locked(
            handler,
            cache_repo,
            user_repo,
            base_headers,
        ):
            user_repo.exists_by_email.return_value = True
            user_repo.set_delivery_failed_by_email.return_value = True
            email = "user@canterlot.dev"
            event = {"type": "email.delivered", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            user_repo.set_delivery_failed_by_email.assert_any_call(email, failed=False)
            cache_repo.invalidate.assert_awaited_once_with(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

        async def it_ignores_unhandled_event_types_silently(handler, cache_repo, user_repo, base_headers):
            user_repo.exists_by_email.return_value = True
            email = "user@canterlot.dev"
            event = {"type": "email.opened", "data": {"to": [email]}}

            with patch("resend.Webhooks.verify", return_value=event):
                await handler.handle_webhook("{}", base_headers)

            user_repo.apply_global_suppression_by_email.assert_not_awaited()
            user_repo.apply_spam_suppression_by_email.assert_not_awaited()
            cache_repo.invalidate.assert_not_awaited()
