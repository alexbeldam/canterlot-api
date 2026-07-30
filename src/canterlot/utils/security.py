import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import bcrypt
import jwt
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.config import get_settings
from canterlot.exceptions import TokenExpiredError, TokenMalformedError

if TYPE_CHECKING:
    from canterlot.emails import EmailCategory
    from canterlot.types import SecretVerificationCode

ACTION_LINK_TOKEN_BYTE_LENGTH: int = 20  # 12 (user) + 8 (code)
TRUNCATED_HMAC_BYTES: int = 10
OBJECT_ID_BYTES: int = 12


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
    code: "SecretVerificationCode"


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
    from canterlot.types import TokenType

    expiry = timedelta(minutes=get_settings().auth.access_token_expiry_minutes)
    return create_jwt_token({"sub": str(user_id), "type": TokenType.ACCESS}, expiry)


def create_refresh_token(user_id: PydanticObjectId) -> str:
    from canterlot.types import TokenType

    expiry = timedelta(days=get_settings().auth.refresh_token_expiry_days)
    return create_jwt_token({"sub": str(user_id), "type": TokenType.REFRESH}, expiry)


def create_reset_token(user_id: PydanticObjectId) -> str:
    from canterlot.types import TokenType

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


def generate_secure_code() -> "SecretVerificationCode":
    """
    Generates a cryptographically secure numeric verification code.
    """
    length = 8
    raw_code = f"{secrets.randbelow(10**length):0{length}d}"

    from canterlot.types import secret_code_adapter

    return secret_code_adapter.validate_python(raw_code)


def _base64_encode(data: bytes) -> str:
    """Encodes binary bytes into an unpadded URL-safe Base64 string."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _base64_decode(token: str) -> bytes:
    """Decodes an unpadded URL-safe Base64 string into binary bytes."""
    try:
        padded_token = token + "=" * (-len(token) % 4)
        return base64.urlsafe_b64decode(padded_token)
    except Exception:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None


def encode_club_unsubscribe_token(user_id: PydanticObjectId, club_id: PydanticObjectId) -> str:
    secret_key = get_settings().auth.hmac_secret_key.get_secret_value()

    tag = bytes([UnsubscribeScope.CLUB])
    payload = tag + user_id.binary + club_id.binary
    full_hmac = hmac.new(secret_key, payload, hashlib.sha256).digest()
    sig_bytes = full_hmac[:TRUNCATED_HMAC_BYTES]

    return _base64_encode(payload + sig_bytes)


def encode_category_unsubscribe_token(user_id: PydanticObjectId, category: "EmailCategory") -> str:
    secret_key = get_settings().auth.hmac_secret_key.get_secret_value()

    category_bytes = category.value.encode("utf-8")
    tag = bytes([UnsubscribeScope.CATEGORY])
    category_len = bytes([len(category_bytes)])

    payload = tag + user_id.binary + category_len + category_bytes
    full_hmac = hmac.new(secret_key, payload, hashlib.sha256).digest()
    sig_bytes = full_hmac[:TRUNCATED_HMAC_BYTES]

    return _base64_encode(payload + sig_bytes)


def decode_unsubscribe_token(token: str) -> UnsubscribeTokenData:
    secret_key = get_settings().auth.hmac_secret_key.get_secret_value()
    token_bytes = _base64_decode(token)

    min_length = 1 + OBJECT_ID_BYTES + TRUNCATED_HMAC_BYTES
    if len(token_bytes) < min_length:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.")

    scope_byte = token_bytes[0]

    try:
        scope = UnsubscribeScope(scope_byte)
    except ValueError:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None

    if scope == UnsubscribeScope.CLUB:
        expected_len = 1 + OBJECT_ID_BYTES + OBJECT_ID_BYTES + TRUNCATED_HMAC_BYTES
        if len(token_bytes) != expected_len:
            raise TokenMalformedError("The token is corrupt, malformed, or altered.")

        payload = token_bytes[: 1 + OBJECT_ID_BYTES + OBJECT_ID_BYTES]
        provided_sig = token_bytes[len(payload) :]

        expected_hmac = hmac.new(secret_key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_sig, expected_hmac[:TRUNCATED_HMAC_BYTES]):
            raise TokenMalformedError("The token is corrupt, malformed, or altered.")

        user_bytes = payload[1 : 1 + OBJECT_ID_BYTES]
        club_bytes = payload[1 + OBJECT_ID_BYTES :]

        return UnsubscribeTokenData(
            scope=scope,
            user_id=PydanticObjectId(user_bytes),
            club_id=PydanticObjectId(club_bytes),
        )

    # scope == UnsubscribeScope.CATEGORY
    cat_len_index = 1 + OBJECT_ID_BYTES
    category_len = token_bytes[cat_len_index]
    payload_len = cat_len_index + 1 + category_len
    expected_len = payload_len + TRUNCATED_HMAC_BYTES

    if len(token_bytes) != expected_len:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.")

    payload = token_bytes[:payload_len]
    provided_sig = token_bytes[payload_len:]

    expected_hmac = hmac.new(secret_key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_hmac[:TRUNCATED_HMAC_BYTES]):
        raise TokenMalformedError("The token is corrupt, malformed, or altered.")

    user_bytes = payload[1:cat_len_index]
    category_str = payload[cat_len_index + 1 :].decode("utf-8")

    try:
        from canterlot.emails import EmailCategory

        category = EmailCategory(category_str)
    except ValueError:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.") from None

    return UnsubscribeTokenData(
        scope=scope,
        user_id=PydanticObjectId(user_bytes),
        category=category,
    )


def encode_action_link_token(user_id: PydanticObjectId, code: "SecretVerificationCode") -> str:
    code_bytes = code.get_secret_value().encode("ascii")
    payload = user_id.binary + code_bytes
    return _base64_encode(payload)


def decode_action_link_token(token: str) -> ActionLinkTokenData:
    from canterlot.types import secret_code_adapter

    token_bytes = _base64_decode(token)

    if len(token_bytes) != ACTION_LINK_TOKEN_BYTE_LENGTH:
        raise TokenMalformedError("The token is corrupt, malformed, or altered.")

    user_bytes = token_bytes[:OBJECT_ID_BYTES]
    code_str = token_bytes[OBJECT_ID_BYTES:ACTION_LINK_TOKEN_BYTE_LENGTH].decode("ascii")

    validated_code = secret_code_adapter.validate_python(code_str)

    return ActionLinkTokenData(
        user_id=PydanticObjectId(user_bytes),
        code=validated_code,
    )
