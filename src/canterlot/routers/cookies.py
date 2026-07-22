from fastapi import Response

from canterlot.config import get_settings

settings = get_settings().auth

PASSWORD_RESET_TOKEN_COOKIE_NAME = "password_reset"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_EXPIRY_SECONDS = settings.refresh_token_expiry_days * 24 * 60 * 60
PASSWORD_RESET_COOKIE_EXPIRY_SECONDS = settings.reset_token_expiry_minutes * 60
AUTH_TOKEN_COOKIE_PATH = "/v1/auth"
HTTP_ONLY = True
SECURE = True
SAME_SITE = "strict"


def set_refresh_token_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=token,
        max_age=REFRESH_COOKIE_EXPIRY_SECONDS,
        path=AUTH_TOKEN_COOKIE_PATH,
        httponly=HTTP_ONLY,
        secure=SECURE,
        samesite=SAME_SITE,
    )


def clear_refresh_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path=AUTH_TOKEN_COOKIE_PATH,
        httponly=HTTP_ONLY,
        secure=SECURE,
        samesite=SAME_SITE,
    )


def set_password_reset_token_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=PASSWORD_RESET_TOKEN_COOKIE_NAME,
        value=token,
        max_age=PASSWORD_RESET_COOKIE_EXPIRY_SECONDS,
        path=AUTH_TOKEN_COOKIE_PATH,
        httponly=HTTP_ONLY,
        secure=SECURE,
        samesite=SAME_SITE,
    )


def clear_password_reset_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=PASSWORD_RESET_TOKEN_COOKIE_NAME,
        path=AUTH_TOKEN_COOKIE_PATH,
        httponly=HTTP_ONLY,
        secure=SECURE,
        samesite=SAME_SITE,
    )
