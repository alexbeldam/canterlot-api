from pydantic import SecretStr

from canterlot.config import get_settings
from canterlot.emails.clients import DisabledEmailClient, DryRunEmailClient, ResendEmailClient
from canterlot.emails.factories import get_email_client


def describe_get_email_client():
    def it_returns_dry_run_when_dry_run_mode_is_enabled(monkeypatch):
        email_settings = get_settings().email
        monkeypatch.setattr(email_settings, "dry_run", True)
        monkeypatch.setattr(email_settings, "resend_api_key", None)

        client = get_email_client()

        assert isinstance(client, DryRunEmailClient)

    def it_returns_resend_when_dry_run_is_disabled_and_api_key_is_present(monkeypatch):
        email_settings = get_settings().email
        monkeypatch.setattr(email_settings, "dry_run", False)
        monkeypatch.setattr(email_settings, "resend_api_key", SecretStr("re_live_123"))

        client = get_email_client()

        assert isinstance(client, ResendEmailClient)

    def it_returns_disabled_when_dry_run_is_disabled_and_api_key_is_missing(monkeypatch):
        email_settings = get_settings().email
        monkeypatch.setattr(email_settings, "dry_run", False)
        monkeypatch.setattr(email_settings, "resend_api_key", None)

        client = get_email_client()

        assert isinstance(client, DisabledEmailClient)
