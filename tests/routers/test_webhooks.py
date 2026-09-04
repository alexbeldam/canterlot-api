from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.gateways.auth.risc import RiscVerificationError
from canterlot.types import AuthProviderName


def describe_receive_google_risc_event():
    def it_processes_a_tokens_revoked_event(
        client: TestClient,
        google_risc_verifier: AsyncMock,
        revoke_auth_provider_use_case: AsyncMock,
    ):
        google_risc_verifier.verify.return_value = {
            "events": {"https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked": {}},
            "subject": {"subject_type": "iss-sub", "sub": "google-sub-1"},
        }

        response = client.post(
            "/webhooks/google/risc",
            content=b"some-signed-set",
            headers={"Content-Type": "application/secevent+jwt"},
        )

        assert response.status_code == 202
        google_risc_verifier.verify.assert_awaited_once_with("some-signed-set")
        revoke_auth_provider_use_case.execute.assert_awaited_once_with(
            provider=AuthProviderName.GOOGLE,
            external_id="google-sub-1",
        )

    def it_ignores_events_of_a_type_it_does_not_handle(
        client: TestClient,
        google_risc_verifier: AsyncMock,
        revoke_auth_provider_use_case: AsyncMock,
    ):
        google_risc_verifier.verify.return_value = {
            "events": {"https://schemas.openid.net/secevent/risc/event-type/account-disabled": {}},
            "subject": {"subject_type": "iss-sub", "sub": "google-sub-1"},
        }

        response = client.post("/webhooks/google/risc", content=b"some-signed-set")

        assert response.status_code == 202
        revoke_auth_provider_use_case.execute.assert_not_called()

    def it_returns_400_when_the_token_fails_verification(
        client: TestClient,
        google_risc_verifier: AsyncMock,
        revoke_auth_provider_use_case: AsyncMock,
    ):
        google_risc_verifier.verify.side_effect = RiscVerificationError("bad token")

        response = client.post("/webhooks/google/risc", content=b"garbage")

        assert response.status_code == 400
        revoke_auth_provider_use_case.execute.assert_not_called()

    def it_is_excluded_from_the_openapi_schema(client: TestClient):
        schema = client.get("/openapi.json").json()

        assert "/webhooks/google/risc" not in schema["paths"]


def describe_receive_resend_event():
    def it_processes_a_valid_resend_webhook_event(
        client: TestClient,
        resend_webhook_handler: AsyncMock,
    ):
        response = client.post(
            "/webhooks/resend/events",
            content=b'{"type": "email.delivered"}',
            headers={
                "svix-id": "msg_123",
                "svix-timestamp": "1234567890",
                "svix-signature": "v1,sig_abc",
            },
        )

        assert response.status_code == 200
        resend_webhook_handler.handle_webhook.assert_awaited_once()

    def it_returns_400_when_svix_headers_are_missing(
        client: TestClient,
        resend_webhook_handler: AsyncMock,
    ):
        response = client.post(
            "/webhooks/resend/events",
            content=b'{"type": "email.delivered"}',
            headers={
                "svix-id": "",
                "svix-timestamp": "1234567890",
                "svix-signature": "v1,sig_abc",
            },
        )

        assert response.status_code == 400
        resend_webhook_handler.handle_webhook.assert_not_called()
