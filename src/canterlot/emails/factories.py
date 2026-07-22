from canterlot.config import get_settings

from .clients import DisabledEmailClient, DryRunEmailClient, ResendEmailClient
from .interfaces import EmailClient


def get_email_client() -> EmailClient:
    settings = get_settings().email

    if settings.dry_run:
        return DryRunEmailClient()

    if settings.resend_api_key:
        return ResendEmailClient(settings.resend_api_key.get_secret_value())

    return DisabledEmailClient("Resend email client is not configured because RESEND_API_KEY is missing.")
