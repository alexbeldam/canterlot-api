from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from curl_cffi.requests import AsyncSession

from canterlot.gateways.auth.risc.google import RISC_CONFIGURATION_URL, GoogleRiscVerifier, RiscVerificationError

ISSUER = "https://accounts.google.com"
CLIENT_ID = "some-client-id"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"


def _response(status_code: int, body: dict) -> AsyncMock:
    response = AsyncMock()
    response.status_code = status_code
    response.json = lambda: body
    return response


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def verifier(session: AsyncMock) -> GoogleRiscVerifier:
    return GoogleRiscVerifier(CLIENT_ID, session)


@pytest.fixture
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _sign(private_key, **claim_overrides) -> str:
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "iat": 1700000000,
        "jti": "some-jti",
        "events": {"https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked": {}},
        "subject": {"subject_type": "iss-sub", "iss": ISSUER, "sub": "google-sub-1"},
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def _configure_discovery(session: AsyncMock) -> None:
    session.get.return_value = _response(200, {"issuer": ISSUER, "jwks_uri": JWKS_URI})


def _patch_jwk_client(public_key):
    signing_key = MagicMock(key=public_key)
    fake_client = MagicMock()
    fake_client.get_signing_key_from_jwt.return_value = signing_key
    return patch("canterlot.gateways.auth.risc.google.jwt.PyJWKClient", return_value=fake_client)


def describe_verify():
    async def it_returns_the_decoded_claims_for_a_validly_signed_token(
        verifier: GoogleRiscVerifier, session: AsyncMock, key_pair
    ):
        private_key, public_key = key_pair
        _configure_discovery(session)
        token = _sign(private_key)

        with _patch_jwk_client(public_key):
            claims = await verifier.verify(token)

        assert claims["subject"]["sub"] == "google-sub-1"
        session.get.assert_awaited_once_with(RISC_CONFIGURATION_URL)

    async def it_only_fetches_the_discovery_document_once(verifier: GoogleRiscVerifier, session: AsyncMock, key_pair):
        private_key, public_key = key_pair
        _configure_discovery(session)
        token = _sign(private_key)

        with _patch_jwk_client(public_key):
            await verifier.verify(token)
            await verifier.verify(token)

        session.get.assert_awaited_once()

    async def it_raises_when_the_signature_does_not_match(verifier: GoogleRiscVerifier, session: AsyncMock, key_pair):
        _, public_key = key_pair
        other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _configure_discovery(session)
        token = _sign(other_private_key)

        with _patch_jwk_client(public_key), pytest.raises(RiscVerificationError):
            await verifier.verify(token)

    async def it_raises_when_the_audience_does_not_match(verifier: GoogleRiscVerifier, session: AsyncMock, key_pair):
        private_key, public_key = key_pair
        _configure_discovery(session)
        token = _sign(private_key, aud="some-other-client-id")

        with _patch_jwk_client(public_key), pytest.raises(RiscVerificationError):
            await verifier.verify(token)

    async def it_raises_when_the_issuer_does_not_match(verifier: GoogleRiscVerifier, session: AsyncMock, key_pair):
        private_key, public_key = key_pair
        _configure_discovery(session)
        token = _sign(private_key, iss="https://not-google.example")

        with _patch_jwk_client(public_key), pytest.raises(RiscVerificationError):
            await verifier.verify(token)

    async def it_raises_when_the_discovery_document_cannot_be_fetched(verifier: GoogleRiscVerifier, session: AsyncMock):
        session.get.return_value = _response(500, {})

        with pytest.raises(RiscVerificationError):
            await verifier.verify("irrelevant-token")
