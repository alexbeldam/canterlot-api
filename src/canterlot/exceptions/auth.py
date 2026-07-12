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

    def __init__(self, message: str | None = None):
        super().__init__(message)
        self.headers = {"WWW-Authenticate": "Bearer"}


class TokenError(BusinessError):
    pass


class TokenExpiredError(TokenError):
    error_code = ErrorCode.TOKEN_EXPIRED
    status_code = status.HTTP_401_UNAUTHORIZED


class TokenMalformedError(TokenError):
    error_code = ErrorCode.TOKEN_MALFORMED
    status_code = status.HTTP_400_BAD_REQUEST


class InvalidOAuthCredentialError(AuthenticationError):
    error_code = ErrorCode.INVALID_OAUTH_CREDENTIAL
    status_code = status.HTTP_401_UNAUTHORIZED


class AuthProviderAlreadyLinkedError(AuthenticationError):
    error_code = ErrorCode.AUTH_PROVIDER_ALREADY_LINKED
    status_code = status.HTTP_409_CONFLICT


class OAuthAccountCreationConflictError(AuthenticationError):
    error_code = ErrorCode.OAUTH_ACCOUNT_CREATION_CONFLICT
    status_code = status.HTTP_409_CONFLICT


class AuthProviderNotLinkedError(AuthenticationError):
    error_code = ErrorCode.AUTH_PROVIDER_NOT_LINKED
    status_code = status.HTTP_404_NOT_FOUND


class LastAuthenticationMethodError(AuthenticationError):
    error_code = ErrorCode.LAST_AUTHENTICATION_METHOD
    status_code = status.HTTP_409_CONFLICT
