from dataclasses import dataclass
from typing import Protocol

from canterlot.types import NormalizedEmailStr


@dataclass(frozen=True)
class EmailMessage:
    sender: str
    to: list[NormalizedEmailStr]
    subject: str
    html: str
    reply_to: NormalizedEmailStr
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    provider_message_id: str | None = None
    dry_run: bool = False
    disabled: bool = False
    error_message: str | None = None


class EmailClient(Protocol):
    @property
    def name(self) -> str: ...

    async def send(self, message: EmailMessage) -> EmailSendResult: ...
