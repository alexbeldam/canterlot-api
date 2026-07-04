from enum import StrEnum
from typing import ClassVar


class ErrorCode(StrEnum):
    USERNAME_ALREADY_EXISTS = "USERNAME_ALREADY_EXISTS"
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_MALFORMED = "TOKEN_MALFORMED"
    INVALID_INVITE_TOKEN = "INVALID_INVITE_TOKEN"
    INVITE_LINK_DEACTIVATED = "INVITE_LINK_DEACTIVATED"
    BOOK_NOT_FOUND = "BOOK_NOT_FOUND"
    EXTERNAL_BOOK_DETAILS_NOT_FOUND = "EXTERNAL_BOOK_DETAILS_NOT_FOUND"
    CLUB_NOT_FOUND = "CLUB_NOT_FOUND"
    CLUB_SUGGESTIONS_CLOSED = "CLUB_SUGGESTIONS_CLOSED"
    UNAUTHORIZED_CLUB_MEMBER = "UNAUTHORIZED_CLUB_MEMBER"
    INVITE_IDENTITY_MISMATCH = "INVITE_IDENTITY_MISMATCH"
    GATEWAY_CONFIGURATION_ERROR = "GATEWAY_CONFIGURATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class BusinessError(Exception):
    error_code: ClassVar[ErrorCode]
    status_code: ClassVar[int]
    client_message: ClassVar[str | None] = None
    headers: ClassVar[dict[str, str] | None] = None

    def __init__(self, message: str | None = None):
        super().__init__(message or self.client_message or self.error_code.value)

    @property
    def response_message(self) -> str:
        return self.client_message or str(self)
