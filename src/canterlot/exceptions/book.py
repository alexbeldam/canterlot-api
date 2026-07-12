from fastapi import status

from .base import BusinessError, ErrorCode


class BookDomainError(BusinessError):
    pass


class BookNotFoundError(BookDomainError):
    error_code = ErrorCode.BOOK_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND


class BookDetailsNotFoundError(BookDomainError):
    error_code = ErrorCode.EXTERNAL_BOOK_DETAILS_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND


class BookSearchCriteriaMissingError(BookDomainError):
    error_code = ErrorCode.BOOK_SEARCH_CRITERIA_MISSING
    status_code = status.HTTP_400_BAD_REQUEST


class BookProviderUnavailableError(BookDomainError):
    error_code = ErrorCode.BOOK_PROVIDER_UNAVAILABLE
    status_code = status.HTTP_502_BAD_GATEWAY
