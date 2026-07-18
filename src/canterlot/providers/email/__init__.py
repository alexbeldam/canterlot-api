from .disabled import DisabledEmailClient
from .dry_run import DryRunEmailClient
from .factories import get_email_client
from .interfaces import EmailClient, EmailMessage, EmailSendResult
from .resend import ResendEmailClient

__all__ = [
    "DisabledEmailClient",
    "DryRunEmailClient",
    "EmailClient",
    "EmailMessage",
    "EmailSendResult",
    "ResendEmailClient",
    "get_email_client",
]
