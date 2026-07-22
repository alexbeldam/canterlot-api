from datetime import UTC, datetime, timedelta

import jwt
import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.config import get_settings
from canterlot.emails.core.enums import EmailCategory
from canterlot.exceptions import TokenExpiredError, TokenMalformedError
from canterlot.types import secret_code_adapter
from canterlot.utils.security import (
    UnsubscribeScope,
    create_access_token,
    create_jwt_token,
    create_refresh_token,
    create_reset_token,
    decode_action_link_token,
    decode_jwt_payload,
    decode_unsubscribe_token,
    encode_action_link_token,
    encode_category_unsubscribe_token,
    encode_club_unsubscribe_token,
    generate_secure_code,
    hash_password,
    verify_password,
)


def describe_password_hashing():
    def it_hashes_a_password_into_a_different_string():
        hashed = hash_password(SecretStr("correct horse battery staple"))
        assert hashed != "correct horse battery staple"

    def it_produces_a_different_hash_each_time_due_to_salting():
        assert hash_password(SecretStr("correct horse battery staple")) != hash_password(
            SecretStr("correct horse battery staple")
        )

    def it_verifies_a_correct_password_against_its_hash():
        hashed = hash_password(SecretStr("correct horse battery staple"))
        assert verify_password(SecretStr("correct horse battery staple"), hashed) is True

    def it_rejects_an_incorrect_password():
        hashed = hash_password(SecretStr("correct horse battery staple"))
        assert verify_password(SecretStr("wrong password"), hashed) is False


def describe_jwt_tokens():
    def it_round_trips_arbitrary_claims():
        token = create_jwt_token({"sub": "abc123"}, timedelta(minutes=5))
        payload = decode_jwt_payload(token)
        assert payload["sub"] == "abc123"
        assert "exp" in payload

    def it_creates_an_access_token_with_the_expected_claims():
        user_id = PydanticObjectId()
        token = create_access_token(user_id)
        payload = decode_jwt_payload(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"

    def it_expires_after_the_configured_number_of_minutes():
        token = create_access_token(PydanticObjectId())
        payload = decode_jwt_payload(token)

        expected_expiry = datetime.now(UTC) + timedelta(minutes=get_settings().auth.access_token_expiry_minutes)
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert abs((actual_expiry - expected_expiry).total_seconds()) < 5

    def it_creates_a_refresh_token_with_the_expected_claims():
        user_id = PydanticObjectId()
        token = create_refresh_token(user_id)
        payload = decode_jwt_payload(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"

    def it_creates_a_reset_token_with_the_expected_claims():
        user_id = PydanticObjectId()
        token = create_reset_token(user_id)
        payload = decode_jwt_payload(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "reset"

    def it_raises_token_expired_error_for_an_expired_token():
        token = create_jwt_token({"sub": "abc123"}, timedelta(seconds=-1))
        with pytest.raises(TokenExpiredError):
            decode_jwt_payload(token)

    def it_raises_token_malformed_error_for_a_garbage_token():
        with pytest.raises(TokenMalformedError):
            decode_jwt_payload("not.a.jwt")

    def it_raises_token_malformed_error_for_a_token_signed_with_a_different_secret():
        bad_token = jwt.encode(
            {"sub": "abc123"},
            "some-other-secret-that-is-at-least-32-bytes-long",
            algorithm=get_settings().auth.jwt_algorithm,
        )
        with pytest.raises(TokenMalformedError):
            decode_jwt_payload(bad_token)


def describe_generate_secure_alphanumeric_code():
    def it_generates_an_8_digit_code():
        secret_code = generate_secure_code()

        assert isinstance(secret_code, SecretStr)

        code = secret_code.get_secret_value()
        assert isinstance(code, str)
        assert len(code) == 8

        assert code.isnumeric()


def describe_unsubscribe_tokens():
    def it_encodes_and_decodes_club_unsubscribe_tokens():
        user_id = PydanticObjectId("507f1f77bcf86cd799439011")
        club_id = PydanticObjectId("507f1f77bcf86cd799439022")

        token = encode_club_unsubscribe_token(user_id, club_id)
        data = decode_unsubscribe_token(token)

        assert data.scope == UnsubscribeScope.CLUB
        assert data.user_id == user_id
        assert data.club_id == club_id
        assert data.category is None

    def it_encodes_and_decodes_category_unsubscribe_tokens():
        user_id = PydanticObjectId("507f1f77bcf86cd799439011")
        category = EmailCategory.PROMOTIONAL

        token = encode_category_unsubscribe_token(user_id, category)
        data = decode_unsubscribe_token(token)

        assert data.scope == UnsubscribeScope.CATEGORY
        assert data.user_id == user_id
        assert data.category == category
        assert data.club_id is None

    def it_raises_token_malformed_error_for_invalid_base64_unsubscribe_token():
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token("!!!not_base64!!!")

    def it_raises_token_malformed_error_for_too_short_unsubscribe_token():
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token("aGVsbG8=")

    def it_raises_token_malformed_error_for_invalid_scope_tag():
        import base64

        raw = bytes([99]) + (b"\x00" * 22)
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token(token)

    def it_raises_token_malformed_error_when_club_token_length_is_incorrect():
        import base64

        raw = bytes([UnsubscribeScope.CLUB]) + (b"\x00" * 10)
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token(token)

    def it_raises_token_malformed_error_when_club_token_signature_is_invalid():
        user_id = PydanticObjectId("507f1f77bcf86cd799439011")
        club_id = PydanticObjectId("507f1f77bcf86cd799439022")
        token = encode_club_unsubscribe_token(user_id, club_id)

        # Corrupt signature by replacing last character
        corrupted_token = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token(corrupted_token)

    def it_raises_token_malformed_error_when_category_token_length_is_incorrect():
        import base64

        raw = bytes([UnsubscribeScope.CATEGORY]) + (b"\x00" * 25)
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token(token)

    def it_raises_token_malformed_error_when_category_enum_is_invalid():
        import base64
        import hashlib
        import hmac

        secret_key = get_settings().auth.jwt_secret_key.get_secret_value().encode("utf-8")
        user_id = PydanticObjectId()
        bad_category = b"non_existent_cat"

        tag = bytes([UnsubscribeScope.CATEGORY])
        cat_len = bytes([len(bad_category)])
        payload = tag + user_id.binary + cat_len + bad_category
        sig = hmac.new(secret_key, payload, hashlib.sha256).digest()[:10]

        token = base64.urlsafe_b64encode(payload + sig).decode("ascii").rstrip("=")
        with pytest.raises(TokenMalformedError):
            decode_unsubscribe_token(token)


def describe_action_link_tokens():
    def it_encodes_and_decodes_action_link_tokens():
        user_id = PydanticObjectId("507f1f77bcf86cd799439011")
        code = secret_code_adapter.validate_python("12345678")

        token = encode_action_link_token(user_id, code)
        data = decode_action_link_token(token)

        assert data.user_id == user_id
        assert data.code.get_secret_value() == "12345678"

    def it_raises_token_malformed_error_for_invalid_action_token_length():
        with pytest.raises(TokenMalformedError):
            decode_action_link_token("aGVsbG8=")
