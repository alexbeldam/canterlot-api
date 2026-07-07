import pytest

from canterlot.exceptions import InvalidOAuthCredentialError
from canterlot.models.enums import AuthProviderName
from canterlot.providers.auth import google as google_module
from canterlot.providers.auth.google import GoogleAuthProvider


@pytest.fixture
def provider() -> GoogleAuthProvider:
    return GoogleAuthProvider("some-client-id.apps.googleusercontent.com")


def describe_name():
    def it_reports_google_as_its_provider_name(provider: GoogleAuthProvider):
        assert provider.name == AuthProviderName.GOOGLE


def describe_verify():
    async def it_returns_the_identity_extracted_from_the_verified_claims(
        monkeypatch: pytest.MonkeyPatch, provider: GoogleAuthProvider
    ):
        monkeypatch.setattr(
            google_module.google_id_token,
            "verify_oauth2_token",
            lambda *_args, **_kwargs: {"sub": "google-sub-123", "email": "alice@example.com", "name": "Alice"},
        )

        identity = await provider.verify("some-id-token")

        assert identity.external_id == "google-sub-123"
        assert identity.email == "alice@example.com"
        assert identity.name == "Alice"

    async def it_defaults_the_name_to_none_when_absent_from_the_claims(
        monkeypatch: pytest.MonkeyPatch, provider: GoogleAuthProvider
    ):
        monkeypatch.setattr(
            google_module.google_id_token,
            "verify_oauth2_token",
            lambda *_args, **_kwargs: {"sub": "google-sub-123", "email": "alice@example.com"},
        )

        identity = await provider.verify("some-id-token")

        assert identity.name is None

    async def it_raises_invalid_oauth_credential_when_verification_fails(
        monkeypatch: pytest.MonkeyPatch, provider: GoogleAuthProvider
    ):
        def raise_value_error(*_args, **_kwargs):
            raise ValueError("Token used too late")

        monkeypatch.setattr(google_module.google_id_token, "verify_oauth2_token", raise_value_error)

        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("expired-token")
