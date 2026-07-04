from datetime import timedelta

import jwt
import pytest
from beanie import PydanticObjectId

from canterlot.config import settings
from canterlot.exceptions import TokenExpiredError, TokenMalformedError
from canterlot.utils.security import (
    create_access_token,
    create_jwt_token,
    create_refresh_token,
    decode_jwt_payload,
    hash_password,
    verify_password,
)


def describe_password_hashing():
    def it_hashes_a_password_into_a_different_string():
        hashed = hash_password("correct horse battery staple")
        assert hashed != "correct horse battery staple"

    def it_produces_a_different_hash_each_time_due_to_salting():
        assert hash_password("correct horse battery staple") != hash_password("correct horse battery staple")

    def it_verifies_a_correct_password_against_its_hash():
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True

    def it_rejects_an_incorrect_password():
        hashed = hash_password("correct horse battery staple")
        assert verify_password("wrong password", hashed) is False


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

    def it_creates_a_refresh_token_with_the_expected_claims():
        user_id = PydanticObjectId()
        token = create_refresh_token(user_id)
        payload = decode_jwt_payload(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"

    def it_raises_token_expired_error_for_an_expired_token():
        token = create_jwt_token({"sub": "abc123"}, timedelta(seconds=-1))
        with pytest.raises(TokenExpiredError):
            decode_jwt_payload(token)

    def it_raises_token_malformed_error_for_a_garbage_token():
        with pytest.raises(TokenMalformedError):
            decode_jwt_payload("not.a.jwt")

    def it_raises_token_malformed_error_for_a_token_signed_with_a_different_secret():
        bad_token = jwt.encode(
            {"sub": "abc123"}, "some-other-secret-that-is-at-least-32-bytes-long", algorithm=settings.jwt_algorithm
        )
        with pytest.raises(TokenMalformedError):
            decode_jwt_payload(bad_token)
