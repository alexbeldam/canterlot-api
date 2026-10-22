import base64
import functools
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import bcrypt
import jwt
from beanie import PydanticObjectId
from bson.errors import InvalidId
from itsdangerous import BadData, URLSafeSerializer
from pydantic import SecretStr

from canterlot.config import get_settings
from canterlot.exceptions import TokenExpiredError, TokenMalformedError
from canterlot.types import SecretVerificationCode, TokenType, secret_code_adapter

if TYPE_CHECKING:
    from canterlot.emails import EmailCategory

_UNSUBSCRIBE_SALT = "email-unsubscribe"
_ACTION_LINK_SALT = "email-action-link"
_DIGEST_METHOD = functools.partial(hashlib.blake2s, digest_size=10)


class UnsubscribeScope(IntEnum):
    CLUB = 1
    CATEGORY = 2


@dataclass(frozen=True)
class UnsubscribeTokenData:
    scope: UnsubscribeScope
    user_id: PydanticObjectId
    club_id: PydanticObjectId | None = None
    category: "EmailCategory | None" = None


@dataclass(frozen=True)
class ActionLinkTokenData:
    user_id: PydanticObjectId
    code: SecretVerificationCode


def hash_password(password: SecretStr | str) -> str:
    if isinstance(password, SecretStr):
        password_bytes = password.get_secret_value().encode("utf-8")
    else:
        password_bytes = password.encode("utf-8")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)

    return hashed.decode("utf-8")


def verify_password(plain_password: SecretStr, hashed_password: str) -> bool:
    password_bytes = plain_password.get_secret_value().encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_jwt_token(data: dict, expires_delta: timedelta) -> str:
    settings = get_settings().auth
    to_encode = data.copy()
    expire = datetime.now(UTC) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)


def create_access_token(user_id: PydanticObjectId) -> str:
    expiry = timedelta(minutes=get_settings().auth.access_token_expiry_minutes)
    return create_jwt_token({"sub": str(user_id), "type": TokenType.ACCESS}, expiry)


def create_refresh_token(user_id: PydanticObjectId) -> str:
    expiry = timedelta(days=get_settings().auth.refresh_token_expiry_days)
    return create_jwt_token({"sub": str(user_id), "type": TokenType.REFRESH}, expiry)


def create_reset_token(user_id: PydanticObjectId) -> str:
    expiry = timedelta(minutes=get_settings().auth.reset_token_expiry_minutes)
    return create_jwt_token({"sub": str(user_id), "type": TokenType.RESET}, expiry)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    settings = get_settings().auth
    try:
        return jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("The token validation window has expired.") from None
    except jwt.PyJWTError:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None


def generate_secure_code() -> SecretVerificationCode:
    """
    Generates a cryptographically secure numeric verification code.
    """
    length = 6
    raw_code = f"{secrets.randbelow(10**length):0{length}d}"

    return secret_code_adapter.validate_python(raw_code)


def _unsubscribe_serializer() -> URLSafeSerializer:
    secret_key = get_settings().auth.hmac_secret_key.get_secret_value()
    return URLSafeSerializer(secret_key, salt=_UNSUBSCRIBE_SALT, signer_kwargs={"digest_method": _DIGEST_METHOD})


def _action_link_serializer() -> URLSafeSerializer:
    secret_key = get_settings().auth.hmac_secret_key.get_secret_value()
    return URLSafeSerializer(secret_key, salt=_ACTION_LINK_SALT, signer_kwargs={"digest_method": _DIGEST_METHOD})


def _pack_id(object_id: PydanticObjectId) -> str:
    return base64.urlsafe_b64encode(object_id.binary).decode("ascii")


def _unpack_id(packed: str) -> PydanticObjectId:
    return PydanticObjectId(base64.urlsafe_b64decode(packed))


def encode_club_unsubscribe_token(user_id: PydanticObjectId, club_id: PydanticObjectId) -> str:
    return _unsubscribe_serializer().dumps(f"{UnsubscribeScope.CLUB.value}:{_pack_id(user_id)}:{_pack_id(club_id)}")


def encode_category_unsubscribe_token(user_id: PydanticObjectId, category: "EmailCategory") -> str:
    from canterlot.emails import EmailCategory

    ordinal = list(EmailCategory).index(category)
    return _unsubscribe_serializer().dumps(f"{UnsubscribeScope.CATEGORY.value}:{_pack_id(user_id)}:{ordinal}")


def decode_unsubscribe_token(token: str) -> UnsubscribeTokenData:
    from canterlot.emails import EmailCategory

    try:
        scope_str, user_id, third = _unsubscribe_serializer().loads(token).split(":")
        scope = UnsubscribeScope(int(scope_str))

        if scope == UnsubscribeScope.CLUB:
            return UnsubscribeTokenData(
                scope=scope,
                user_id=_unpack_id(user_id),
                club_id=_unpack_id(third),
            )

        return UnsubscribeTokenData(
            scope=scope,
            user_id=_unpack_id(user_id),
            category=list(EmailCategory)[int(third)],
        )
    except (BadData, ValueError, TypeError, IndexError, InvalidId):
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None


def encode_action_link_token(user_id: PydanticObjectId, code: SecretVerificationCode) -> str:
    return _action_link_serializer().dumps(f"{_pack_id(user_id)}:{code.get_secret_value()}")


def decode_action_link_token(token: str) -> ActionLinkTokenData:
    try:
        user_id, raw_code = _action_link_serializer().loads(token).split(":")
        return ActionLinkTokenData(
            user_id=_unpack_id(user_id),
            code=secret_code_adapter.validate_python(raw_code),
        )
    except (BadData, ValueError, TypeError, InvalidId):
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None
