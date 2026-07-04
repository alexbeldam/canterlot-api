import pytest
from pydantic import ValidationError

from canterlot.models.user import UserModel, UserRegisterRequest


def describe_username_normalization_and_constraints():
    def it_lowercases_the_username_on_both_the_document_and_the_request():
        request = UserRegisterRequest(name="Alice Smith", username="ALICE_1", email="a@b.com", password="secret1")
        assert request.username == "alice_1"

        document = UserModel(name="Alice Smith", username="ALICE_1", email="a@b.com", hashed_password="hash")
        assert document.username == "alice_1"

    @pytest.mark.parametrize("bad_username", ["ab", "a" * 31])
    def it_rejects_usernames_outside_the_length_bounds(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username=bad_username, email="a@b.com", password="secret1")

    @pytest.mark.parametrize("bad_username", ["has space", "has-dash", "has.dot", ""])
    def it_rejects_usernames_with_disallowed_characters(bad_username: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username=bad_username, email="a@b.com", password="secret1")


def describe_person_name_constraints():
    @pytest.mark.parametrize("bad_name", ["A", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name=bad_name, username="alice_1", email="a@b.com", password="secret1")


def describe_email_normalization():
    def it_normalizes_the_email_on_both_the_document_and_the_request():
        request = UserRegisterRequest(
            name="Alice Smith", username="alice_1", email="  Alice@Example.COM  ", password="secret1"
        )
        assert request.email == "alice@example.com"

        document = UserModel(
            name="Alice Smith", username="alice_1", email="  Alice@Example.COM  ", hashed_password="hash"
        )
        assert document.email == "alice@example.com"


def describe_password_constraints():
    def it_rejects_passwords_shorter_than_six_characters():
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Alice Smith", username="alice_1", email="a@b.com", password="short")

    def it_accepts_a_password_at_the_minimum_length():
        request = UserRegisterRequest(name="Alice Smith", username="alice_1", email="a@b.com", password="123456")
        assert request.password == "123456"


def describe_user_model_defaults():
    def it_defaults_referral_count_and_lists_to_empty():
        document = UserModel(name="Alice Smith", username="alice_1", email="a@b.com", hashed_password="hash")
        assert document.referral_count == 0
        assert document.refresh_tokens == []
        assert document.books_read == []
