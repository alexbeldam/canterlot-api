from canterlot.config import get_settings
from canterlot.models.enums import AuthProviderName
from canterlot.providers.auth.factories import get_all_oauth_providers
from canterlot.providers.auth.google import GoogleAuthProvider


def describe_get_all_oauth_providers():
    def it_returns_an_empty_dict_when_no_client_id_is_configured():
        assert get_all_oauth_providers() == {}

    def it_registers_google_when_a_client_id_is_configured(monkeypatch):
        monkeypatch.setattr(get_settings(), "google_oauth_client_id", "some-client-id")

        providers = get_all_oauth_providers()

        assert list(providers) == [AuthProviderName.GOOGLE]
        assert isinstance(providers[AuthProviderName.GOOGLE], GoogleAuthProvider)
