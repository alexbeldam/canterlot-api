import pytest
from pydantic import HttpUrl, ValidationError

from canterlot.models.enums import AuthProviderName
from canterlot.models.user import AvatarSchema, LinkedProviderSchema, UserModel


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

    def it_defaults_avatar_to_none_with_a_generated_seed_always_available():
        document = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")
        assert document.avatar is None
        assert document.generated_avatar_seed is not None

    def it_generates_a_distinct_seed_per_instance():
        first = UserModel(name="Alice Smith", username="alice_1", email="a@b.com")
        second = UserModel(name="Bob Jones", username="bob_1", email="b@c.com")
        assert first.generated_avatar_seed != second.generated_avatar_seed

    def it_accepts_an_avatar():
        document = UserModel(
            name="Alice Smith",
            username="alice_1",
            email="a@b.com",
            avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=HttpUrl("https://example.com/pic.jpg")),
        )
        assert document.avatar is not None
        assert document.avatar.source == AuthProviderName.GOOGLE
        assert str(document.avatar.value) == "https://example.com/pic.jpg"


def describe_avatar_schema():
    def it_requires_both_source_and_value():
        with pytest.raises(ValidationError):
            AvatarSchema.model_validate({"source": AuthProviderName.GRAVATAR})


def describe_linked_provider_schema():
    def it_defaults_picture_url_to_none():
        linked = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="sub-1")
        assert linked.picture_url is None

    def it_accepts_a_picture_url():
        linked = LinkedProviderSchema(
            provider=AuthProviderName.GOOGLE,
            external_id="sub-1",
            picture_url=HttpUrl("https://example.com/pic.jpg"),
        )
        assert str(linked.picture_url) == "https://example.com/pic.jpg"


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
