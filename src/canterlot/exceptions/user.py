from fastapi import status

from .base import BusinessError, ErrorCode


class UserDomainError(BusinessError):
    pass


class UserNotFoundError(UserDomainError):
    error_code = ErrorCode.USER_NOT_FOUND
    status_code = status.HTTP_404_NOT_FOUND
