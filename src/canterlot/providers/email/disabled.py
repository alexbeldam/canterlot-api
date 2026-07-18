from canterlot.utils import get_logger

from .interfaces import EmailClient, EmailMessage, EmailSendResult

logger = get_logger(__name__)


class DisabledEmailClient(EmailClient):
    def __init__(self, reason: str):
        self.__reason = reason

    @property
    def name(self) -> str:
        return "disabled"

    async def send(self, _message: EmailMessage) -> EmailSendResult:
        logger.warn("Email send skipped because client is disabled", provider=self.name, reason=self.__reason)
        return EmailSendResult(success=False, disabled=True, error_message=self.__reason)
