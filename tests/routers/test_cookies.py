from starlette.responses import Response

from canterlot.config import get_settings
from canterlot.routers.cookies import clear_refresh_token_cookie, set_refresh_token_cookie


def describe_set_refresh_token_cookie():
    def it_sets_an_httponly_secure_strict_cookie_scoped_to_the_auth_path():
        response = Response()

        set_refresh_token_cookie(response, "some-refresh-token")

        set_cookie = response.headers.get("set-cookie", "")
        expected_max_age = get_settings().refresh_token_expiry_days * 24 * 60 * 60
        assert "refresh_token=some-refresh-token" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "samesite=strict" in set_cookie.lower()
        assert "Path=/api/v1/auth" in set_cookie
        assert f"Max-Age={expected_max_age}" in set_cookie


def describe_clear_refresh_token_cookie():
    def it_expires_the_cookie_with_matching_attributes():
        response = Response()

        clear_refresh_token_cookie(response)

        set_cookie = response.headers.get("set-cookie", "")
        assert 'refresh_token=""' in set_cookie
        assert "Max-Age=0" in set_cookie
        assert "Path=/api/v1/auth" in set_cookie
        assert "samesite=strict" in set_cookie.lower()
