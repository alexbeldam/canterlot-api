from unittest.mock import AsyncMock

from curl_cffi.requests import AsyncSession

from canterlot.config import get_settings
from canterlot.models.enums import AuthProviderName
from canterlot.providers.auth.factories import get_all_oauth_providers
from canterlot.providers.auth.google import GoogleAuthProvider
from canterlot.providers.auth.gravatar import GravatarAuthProvider


def _session() -> AsyncSession:
    return AsyncMock(spec=AsyncSession)


def describe_get_all_oauth_providers():
    def it_returns_an_empty_dict_when_no_providers_are_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", None)

        assert get_all_oauth_providers(_session()) == {}

    def it_registers_google_when_a_client_id_is_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", "some-client-id")
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", None)

        providers = get_all_oauth_providers(_session())

        assert list(providers) == [AuthProviderName.GOOGLE]
        assert isinstance(providers[AuthProviderName.GOOGLE], GoogleAuthProvider)

    def it_registers_gravatar_when_client_id_and_secret_are_both_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", "some-client-id")
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", "some-client-secret")

        providers = get_all_oauth_providers(_session())

        assert list(providers) == [AuthProviderName.GRAVATAR]
        assert isinstance(providers[AuthProviderName.GRAVATAR], GravatarAuthProvider)

    def it_does_not_register_gravatar_when_only_the_client_id_is_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", "some-client-id")
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", None)

        assert get_all_oauth_providers(_session()) == {}

    def it_does_not_register_gravatar_when_only_the_client_secret_is_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", None)
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", "some-client-secret")

        assert get_all_oauth_providers(_session()) == {}

    def it_registers_both_when_fully_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", "some-client-id")
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_id", "some-client-id")
        monkeypatch.setattr(get_settings(), "gravatar_oauth_client_secret", "some-client-secret")

        providers = get_all_oauth_providers(_session())

        assert set(providers) == {AuthProviderName.GOOGLE, AuthProviderName.GRAVATAR}
