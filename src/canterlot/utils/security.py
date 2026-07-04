from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from beanie import PydanticObjectId

from canterlot.config import settings
from canterlot.exceptions import TokenExpiredError, TokenMalformedError


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)

    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_jwt_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: PydanticObjectId) -> str:
    return create_jwt_token({"sub": str(user_id), "type": "access"}, timedelta(weeks=2))


def create_refresh_token(user_id: PydanticObjectId) -> str:
    return create_jwt_token({"sub": str(user_id), "type": "refresh"}, timedelta(days=60))


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("The token validation window has expired.") from None
    except jwt.PyJWTError:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None
