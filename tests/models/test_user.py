import pytest
from pydantic import ValidationError

from canterlot.models.enums import AuthProviderName
from canterlot.models.user import LinkedProviderSchema, UserModel


def describe_username_normalization():
    def it_lowercases_the_username_on_the_document():
        document = UserModel(name="Alice Smith", username="ALICE_1", email="a@b.com", hashed_password="hash")
        assert document.username == "alice_1"


def describe_email_normalization():
    def it_normalizes_the_email_on_the_document():
        document = UserModel(
            name="Alice Smith", username="alice_1", email="  Alice@Example.COM  ", hashed_password="hash"
        )
        assert document.email == "alice@example.com"


def describe_user_model_defaults():
    def it_defaults_referral_count_and_lists_to_empty():
        document = UserModel(name="Alice Smith", username="alice_1", email="a@b.com", hashed_password="hash")
        assert document.referral_count == 0
        assert document.refresh_tokens == []
        assert document.books_read == []
        assert document.linked_providers == []

    def it_allows_a_user_created_purely_from_an_oauth_provider_to_have_no_password():
        document = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")
        assert document.hashed_password is None


def describe_linked_providers_uniqueness():
    def it_allows_distinct_provider_credentials():
        document = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            linked_providers=[
                LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1"),
            ],
        )
        assert len(document.linked_providers) == 1

    def it_rejects_the_same_provider_credential_linked_twice():
        with pytest.raises(ValidationError, match="cannot be linked twice"):
            UserModel(
                name="Alice Smith",
                username="alice_1",
                email="a@b.com",
                linked_providers=[
                    LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1"),
                    LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1"),
                ],
            )
