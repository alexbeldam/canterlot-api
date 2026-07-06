from canterlot.models.user import UserModel


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
