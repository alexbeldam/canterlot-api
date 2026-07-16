from datetime import UTC, datetime

from beanie import PydanticObjectId
from bson.errors import InvalidId
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
                logger.bind(user_id=str(user_id)).warn("Skipped last_seen_at update: repository write failed")

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
