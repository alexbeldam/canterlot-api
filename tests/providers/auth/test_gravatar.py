from unittest.mock import AsyncMock

import pytest
from curl_cffi.requests import AsyncSession

from canterlot.exceptions import InvalidOAuthCredentialError
from canterlot.models.enums import AuthProviderName
from canterlot.providers.auth.gravatar import GravatarAuthProvider

SOME_REDIRECT_URI = "http://localhost:5173/auth/gravatar/callback"


def _response(status_code: int, body: dict) -> AsyncMock:
    response = AsyncMock()
    response.status_code = status_code
    response.json = lambda: body
    return response


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def provider(session: AsyncMock) -> GravatarAuthProvider:
    return GravatarAuthProvider("some-client-id", "some-client-secret", session)


def describe_name():
    def it_reports_gravatar_as_its_provider_name(provider: GravatarAuthProvider):
        assert provider.name == AuthProviderName.GRAVATAR


def describe_supports_avatar():
    def it_reports_that_it_supports_avatars(provider: GravatarAuthProvider):
        assert provider.supports_avatar is True


def describe_verify():
    async def it_returns_the_identity_extracted_from_the_verified_profile(
        provider: GravatarAuthProvider, session: AsyncMock
    ):
        session.post.return_value = _response(200, {"access_token": "some-access-token"})
        session.get.return_value = _response(
            200,
            {
                "ID": 42,
                "email": "alice@example.com",
                "display_name": "Alice",
                "avatar_URL": "https://gravatar.com/avatar/somehash",
                "verified": True,
            },
        )

        identity = await provider.verify("some-auth-code", SOME_REDIRECT_URI)

        assert identity.external_id == "42"
        assert identity.email == "alice@example.com"
        assert identity.name == "Alice"
        assert identity.picture == "https://gravatar.com/avatar/somehash"

        session.post.assert_awaited_once_with(
            "https://public-api.wordpress.com/oauth2/token",
            data={
                "client_id": "some-client-id",
                "client_secret": "some-client-secret",
                "code": "some-auth-code",
                "grant_type": "authorization_code",
                "redirect_uri": SOME_REDIRECT_URI,
            },
        )
        session.get.assert_awaited_once_with(
            "https://public-api.wordpress.com/rest/v1.1/me",
            headers={"Authorization": "Bearer some-access-token"},
        )

    async def it_raises_when_no_redirect_uri_is_supplied(provider: GravatarAuthProvider, session: AsyncMock):
        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("some-auth-code")

        session.post.assert_not_called()

    async def it_raises_when_the_token_exchange_fails(provider: GravatarAuthProvider, session: AsyncMock):
        session.post.return_value = _response(400, {"error": "invalid_grant"})

        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("expired-code", SOME_REDIRECT_URI)

        session.get.assert_not_called()

    async def it_raises_when_the_token_exchange_response_has_no_access_token(
        provider: GravatarAuthProvider, session: AsyncMock
    ):
        session.post.return_value = _response(200, {})

        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("some-auth-code", SOME_REDIRECT_URI)

        session.get.assert_not_called()

    async def it_raises_when_the_profile_fetch_fails(provider: GravatarAuthProvider, session: AsyncMock):
        session.post.return_value = _response(200, {"access_token": "some-access-token"})
        session.get.return_value = _response(401, {})

        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("some-auth-code", SOME_REDIRECT_URI)

    async def it_raises_when_gravatar_has_not_verified_the_email(provider: GravatarAuthProvider, session: AsyncMock):
        session.post.return_value = _response(200, {"access_token": "some-access-token"})
        session.get.return_value = _response(
            200,
            {
                "ID": 42,
                "email": "alice@example.com",
                "display_name": "Alice",
                "avatar_URL": "https://gravatar.com/avatar/somehash",
                "verified": False,
            },
        )

        with pytest.raises(InvalidOAuthCredentialError):
            await provider.verify("some-auth-code", SOME_REDIRECT_URI)
