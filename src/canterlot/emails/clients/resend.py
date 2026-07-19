import asyncio

import resend

from canterlot.utils import get_logger

from ..interfaces import EmailClient, EmailMessage, EmailSendResult

logger = get_logger(__name__)


class ResendEmailClient(EmailClient):
    def __init__(self, api_key: str):
        self.__api_key = api_key

    @property
    def name(self) -> str:
        return "resend"

    async def send(self, message: EmailMessage) -> EmailSendResult:
        log = logger.bind(provider=self.name, recipient_count=len(message.to))
        payload: resend.Emails.SendParams = {
            "from": message.sender,
            "to": message.to,
            "subject": message.subject,
            "html": message.html,
            "reply_to": message.reply_to,
        }

        if message.headers:
            payload["headers"] = message.headers

        try:
            response = await asyncio.to_thread(self.__send, payload)
        except Exception as exc:
            log.error("Resend send failed", error_type=type(exc).__name__, exc_info=True)
            return EmailSendResult(success=False, error_message=str(exc))

        message_id = response.get("id")
        log.info("Resend send succeeded", message_id=message_id)
        return EmailSendResult(success=True, provider_message_id=message_id)

    def __send(self, payload: resend.Emails.SendParams) -> resend.Emails.SendResponse:
        resend.api_key = self.__api_key
        return resend.Emails.send(payload)
