from canterlot.config import get_settings

from .disabled import DisabledEmailClient
from .dry_run import DryRunEmailClient
from .interfaces import EmailClient
from .resend import ResendEmailClient


def get_email_client() -> EmailClient:
    settings = get_settings()

    if settings.email_dry_run:
        return DryRunEmailClient()

    if settings.resend_api_key:
        return ResendEmailClient(settings.resend_api_key)

    return DisabledEmailClient("Resend email client is not configured because RESEND_API_KEY is missing.")
