from typing import cast
from unittest.mock import AsyncMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from canterlot.gateways.auth.risc import GoogleRiscVerifier, RiscVerificationError
from canterlot.routers.dependencies import get_google_risc_verifier
from canterlot.types import AuthProviderName


def _override_verifier(client: TestClient, verifier: AsyncMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_google_risc_verifier] = lambda: verifier


def describe_receive_google_risc_event():
    def it_processes_a_tokens_revoked_event(client: TestClient, auth_service: AsyncMock):
        verifier = AsyncMock(spec=GoogleRiscVerifier)
        verifier.verify.return_value = {
            "events": {"https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked": {}},
            "subject": {"subject_type": "iss-sub", "sub": "google-sub-1"},
        }
        _override_verifier(client, verifier)

        response = client.post(
            "/webhooks/google/risc",
            content=b"some-signed-set",
            headers={"Content-Type": "application/secevent+jwt"},
        )

        assert response.status_code == 202
        verifier.verify.assert_awaited_once_with("some-signed-set")
        auth_service.revoke_provider_link.assert_awaited_once_with(AuthProviderName.GOOGLE, "google-sub-1")

    def it_ignores_events_of_a_type_it_does_not_handle(client: TestClient, auth_service: AsyncMock):
        verifier = AsyncMock(spec=GoogleRiscVerifier)
        verifier.verify.return_value = {
            "events": {"https://schemas.openid.net/secevent/risc/event-type/account-disabled": {}},
            "subject": {"subject_type": "iss-sub", "sub": "google-sub-1"},
        }
        _override_verifier(client, verifier)

        response = client.post("/webhooks/google/risc", content=b"some-signed-set")

        assert response.status_code == 202
        auth_service.revoke_provider_link.assert_not_called()

    def it_returns_400_when_the_token_fails_verification(client: TestClient, auth_service: AsyncMock):
        verifier = AsyncMock(spec=GoogleRiscVerifier)
        verifier.verify.side_effect = RiscVerificationError("bad token")
        _override_verifier(client, verifier)

        response = client.post("/webhooks/google/risc", content=b"garbage")

        assert response.status_code == 400
        auth_service.revoke_provider_link.assert_not_called()

    def it_is_excluded_from_the_openapi_schema(client: TestClient):
        schema = client.get("/openapi.json").json()

        assert "/webhooks/google/risc" not in schema["paths"]
