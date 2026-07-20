import base64
import secrets
from datetime import UTC, datetime

from beanie import PydanticObjectId
from bson.errors import InvalidId
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from canterlot.exceptions import BusinessError
from canterlot.repositories.beanie.user import BeanieUserRepository
from canterlot.utils import get_logger
from canterlot.utils.security import decode_jwt_payload

logger = get_logger(__name__)

_BEARER_PREFIX = "Bearer "


class LastSeenMiddleware(BaseHTTPMiddleware):
    """Best-effort `UserModel.last_seen_at` telemetry; never affects the request it rides on."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        user_id = self.__resolve_authenticated_user_id(request)

        if user_id is not None:
            try:
                await BeanieUserRepository().touch_last_seen(user_id, datetime.now(UTC))
            except Exception:
                logger.bind(user_id=str(user_id)).warning("Skipped last_seen_at update: repository write failed")

        return await call_next(request)

    def __resolve_authenticated_user_id(self, request: Request) -> PydanticObjectId | None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith(_BEARER_PREFIX):
            return None

        token = auth_header.removeprefix(_BEARER_PREFIX)
        try:
            payload = decode_jwt_payload(token)
            if payload.get("type") != "access":
                return None
            return PydanticObjectId(payload["sub"])
        except (BusinessError, InvalidId, KeyError):
            return None


class AdminAuthBackend(AuthenticationBackend):
    """
    An HTTP Basic Auth backend engineered to wrap administrative sub-applications.
    """

    def __init__(self, admin_user: str, admin_pass: str):
        self.admin_user = admin_user
        self.admin_pass = admin_pass

    async def authenticate(self, conn):
        if "Authorization" not in conn.headers:
            return self._raise_challenge()

        auth = conn.headers["Authorization"]
        try:
            scheme, credentials = auth.split()
            if scheme.lower() != "basic":
                return self._raise_challenge()

            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")

            if secrets.compare_digest(username, self.admin_user) and secrets.compare_digest(password, self.admin_pass):
                return AuthCredentials(["admin_authenticated"]), SimpleUser(username)

        except Exception:
            raise AuthenticationError("Invalid basic authentication structural layout.") from None

        return self._raise_challenge()

    def _raise_challenge(self):
        raise AuthenticationError("Authentication required")


def on_auth_error(_request, _exc: Exception) -> Response:
    return Response(
        content="Unauthorized Access",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Admin Dashboard Access Control"'},
    )
