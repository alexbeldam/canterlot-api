from canterlot.config import get_settings
from canterlot.providers.email import DryRunEmailClient, ResendEmailClient
from canterlot.providers.email.disabled import DisabledEmailClient
from canterlot.providers.email.factories import get_email_client


def describe_get_email_client():
    def it_returns_dry_run_when_dry_run_mode_is_enabled(monkeypatch):
        monkeypatch.setattr(get_settings(), "email_dry_run", True)
        monkeypatch.setattr(get_settings(), "resend_api_key", None)

        client = get_email_client()

        assert isinstance(client, DryRunEmailClient)

    def it_returns_resend_when_dry_run_is_disabled_and_api_key_is_present(monkeypatch):
        monkeypatch.setattr(get_settings(), "email_dry_run", False)
        monkeypatch.setattr(get_settings(), "resend_api_key", "re_live_123")

        client = get_email_client()

        assert isinstance(client, ResendEmailClient)

    def it_returns_disabled_when_dry_run_is_disabled_and_api_key_is_missing(monkeypatch):
        monkeypatch.setattr(get_settings(), "email_dry_run", False)
        monkeypatch.setattr(get_settings(), "resend_api_key", None)

        client = get_email_client()

        assert isinstance(client, DisabledEmailClient)
