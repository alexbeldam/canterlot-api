from canterlot.utils import get_logger

from .interfaces import EmailClient, EmailMessage, EmailSendResult

logger = get_logger(__name__)


class DryRunEmailClient(EmailClient):
    @property
    def name(self) -> str:
        return "dry-run"

    async def send(self, message: EmailMessage) -> EmailSendResult:
        logger.info(
            "Email send skipped in dry-run mode",
            provider=self.name,
            recipient_count=len(message.to),
            subject=message.subject,
            has_reply_to=message.reply_to is not None,
            has_headers=message.headers is not None,
        )
        return EmailSendResult(success=True, dry_run=True)
