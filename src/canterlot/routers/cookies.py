from typing import Literal

from fastapi import Response

from canterlot.config import get_settings

PASSWORD_RESET_TOKEN_COOKIE_NAME = "password_reset"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
AUTH_TOKEN_COOKIE_PATH = "/v1/auth"
HTTP_ONLY = True
SECURE = True
SAME_SITE: Literal["lax", "strict", "none"] = "strict"


def set_refresh_token_cookie(response: Response, token: str) -> None:
    settings = get_settings().auth
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_expiry_days * 24 * 60 * 60,
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
    settings = get_settings().auth
    response.set_cookie(
        key=PASSWORD_RESET_TOKEN_COOKIE_NAME,
        value=token,
        max_age=settings.reset_token_expiry_minutes * 60,
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
