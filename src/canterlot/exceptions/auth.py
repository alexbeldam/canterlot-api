from typing import ClassVar

from fastapi import status

from .base import BusinessError, ErrorCode


class AuthenticationError(BusinessError):
    pass


class UsernameAlreadyExistsError(AuthenticationError):
    error_code = ErrorCode.USERNAME_ALREADY_EXISTS
    status_code = status.HTTP_409_CONFLICT


class EmailAlreadyExistsError(AuthenticationError):
    error_code = ErrorCode.EMAIL_ALREADY_EXISTS
    status_code = status.HTTP_409_CONFLICT


class InvalidCredentialsError(AuthenticationError):
    error_code = ErrorCode.INVALID_CREDENTIALS
    status_code = status.HTTP_401_UNAUTHORIZED
    headers: ClassVar[dict[str, str]] = {"WWW-Authenticate": "Bearer"}


class TokenError(BusinessError):
    pass


class TokenExpiredError(TokenError):
    error_code = ErrorCode.TOKEN_EXPIRED
    status_code = status.HTTP_401_UNAUTHORIZED


class TokenMalformedError(TokenError):
    error_code = ErrorCode.TOKEN_MALFORMED
    status_code = status.HTTP_400_BAD_REQUEST
