from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from canterlot.types import (
    MIN_PUBLISHED_YEAR,
    BookProviderIdentifier,
    BookProviderName,
    HttpsUrl,
    ISBN10Str,
    ISBN13Str,
    ISBNStr,
    LanguageStr,
    NonEmptyStr,
    NormalizedEmailStr,
    PasswordStr,
    PublishedYear,
)

language_adapter: TypeAdapter[LanguageStr] = TypeAdapter(LanguageStr)
isbn_adapter: TypeAdapter[ISBNStr] = TypeAdapter(ISBNStr)
isbn10_adapter: TypeAdapter[ISBN10Str] = TypeAdapter(ISBN10Str)
isbn13_adapter: TypeAdapter[ISBN13Str] = TypeAdapter(ISBN13Str)
non_empty_adapter: TypeAdapter[NonEmptyStr] = TypeAdapter(NonEmptyStr)
email_adapter: TypeAdapter[NormalizedEmailStr] = TypeAdapter(NormalizedEmailStr)
https_url_adapter: TypeAdapter[HttpsUrl] = TypeAdapter(HttpsUrl)
password_adapter: TypeAdapter[PasswordStr] = TypeAdapter(PasswordStr)
published_year_adapter: TypeAdapter[PublishedYear] = TypeAdapter(PublishedYear)


def describe_language_validation():
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("en", "en"),
            ("en-US", "en-US"),
            ("English", "en"),
            ("  pt-br  ", "pt-BR"),
            ("spanish", "es"),
        ],
    )
    def it_normalizes_valid_languages(input_val: str, expected: str):
        assert language_adapter.validate_python(input_val) == expected

    @pytest.mark.parametrize("invalid_input", ["", "   ", "NotALanguageAtAll123"])
    def it_raises_error_for_invalid_languages(invalid_input: str):
        with pytest.raises(ValidationError) as exc_info:
            language_adapter.validate_python(invalid_input)
        assert "Language cannot be empty" in str(exc_info.value) or "is not a valid language" in str(exc_info.value)


def describe_isbn_validation():
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("0-306-40615-2", "0306406152"),
            ("0_306_40615_x", "030640615X"),
            ("978-3-16-148410-0", "9783161484100"),
            ("978_3_16_148410_0", "9783161484100"),
            ("9783161484100", "9783161484100"),
        ],
    )
    def it_normalizes_isbn_formats(input_val: str, expected: str):
        assert isbn_adapter.validate_python(input_val) == expected

    def it_enforces_strict_lengths_for_subtypes():
        assert isbn10_adapter.validate_python("0-306-40615-2") == "0306406152"
        assert isbn13_adapter.validate_python("978-3-16-148410-0") == "9783161484100"

        with pytest.raises(ValidationError) as exc_info:
            isbn10_adapter.validate_python("978-3-16-148410-0")
        assert exc_info.value.errors()[0]["type"] == "too_long"

        with pytest.raises(ValidationError) as exc_info:
            isbn13_adapter.validate_python("0-306-40615-2")
        assert exc_info.value.errors()[0]["type"] == "too_short"

    @pytest.mark.parametrize("bad_isbn", ["12345", "1234567890123456", "abc-def-ghi-j"])
    def it_rejects_invalid_isbn_lengths_and_chars(bad_isbn: str):
        with pytest.raises(ValidationError) as exc_info:
            isbn_adapter.validate_python(bad_isbn)
        assert "is not a valid ISBN" in str(exc_info.value)


def describe_non_empty_str():
    def it_strips_surrounding_whitespace():
        assert non_empty_adapter.validate_python("  hello  ") == "hello"

    @pytest.mark.parametrize("invalid_input", ["", "   "])
    def it_rejects_empty_or_whitespace_only_strings(invalid_input: str):
        with pytest.raises(ValidationError):
            non_empty_adapter.validate_python(invalid_input)


def describe_normalized_email_str():
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("Alice@Example.COM", "alice@example.com"),
            ("  bob@example.com  ", "bob@example.com"),
            ("MIXED.Case@Domain.IO", "mixed.case@domain.io"),
        ],
    )
    def it_trims_and_lowercases_valid_emails(input_val: str, expected: str):
        assert email_adapter.validate_python(input_val) == expected

    @pytest.mark.parametrize("invalid_input", ["not-an-email", "missing-domain@", "@missing-local.com", ""])
    def it_rejects_invalid_emails(invalid_input: str):
        with pytest.raises(ValidationError):
            email_adapter.validate_python(invalid_input)


def describe_https_url():
    def it_accepts_a_valid_https_url():
        url = https_url_adapter.validate_python("https://example.com/cover.jpg")
        assert str(url) == "https://example.com/cover.jpg"

    def it_rejects_a_plain_http_url():
        with pytest.raises(ValidationError):
            https_url_adapter.validate_python("http://example.com/cover.jpg")


def describe_password_str():
    @pytest.mark.parametrize(
        "invalid_password",
        [
            "aA1!",  # Too short
            "aA1!" * 20,  # Too long
            "lowercase1!",
            "UPPERCASE1!",
            "NoDigitsHere!",
            "NoSpecialChars123",
        ],
    )
    def it_rejects_invalid_passwords(invalid_password: str):
        with pytest.raises(ValidationError):
            password_adapter.validate_python(invalid_password)

    def it_accepts_and_converts_valid_passwords():
        res = password_adapter.validate_python("Secr3t!123")
        assert res.get_secret_value() == "Secr3t!123"


def describe_validate_published_year():
    def it_accepts_a_reasonable_year():
        assert published_year_adapter.validate_python(2020) == 2020

    def it_rejects_years_before_the_minimum():
        with pytest.raises(ValidationError) as exc_info:
            published_year_adapter.validate_python(MIN_PUBLISHED_YEAR - 1)
        assert exc_info.value.errors()[0]["type"] == "too_small"

    def it_accepts_the_minimum_year_itself():
        assert published_year_adapter.validate_python(MIN_PUBLISHED_YEAR) == MIN_PUBLISHED_YEAR

    def it_rejects_years_too_far_in_the_future():
        max_allowed = datetime.now().year + 2
        with pytest.raises(ValidationError) as exc_info:
            published_year_adapter.validate_python(max_allowed + 1)
        assert exc_info.value.errors()[0]["type"] == "too_large"

    def it_accepts_the_maximum_allowed_future_year():
        max_allowed = datetime.now().year + 2
        assert published_year_adapter.validate_python(max_allowed) == max_allowed


def describe_book_provider_identifier():
    def it_round_trips_through_string_serialization():
        adapter = TypeAdapter(BookProviderIdentifier)
        identifier = adapter.validate_python("google-books__zyTCAlFlgZ8C")

        assert identifier.provider == BookProviderName.GOOGLE
        assert identifier.book_id == "zyTCAlFlgZ8C"
        assert str(identifier) == "google-books__zyTCAlFlgZ8C"

    def it_rejects_a_string_missing_the_separator():
        adapter = TypeAdapter(BookProviderIdentifier)
        with pytest.raises(ValidationError):
            adapter.validate_python("no-separator-here")

    def it_rejects_an_unknown_provider_segment():
        adapter = TypeAdapter(BookProviderIdentifier)
        with pytest.raises(ValidationError):
            adapter.validate_python("not-a-provider__abc123")

    def it_considers_identifiers_with_the_same_provider_and_id_equal():
        first = BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")
        second = BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")

        assert first == second
        assert hash(first) == hash(second)

    def it_considers_identifiers_with_a_different_id_unequal():
        first = BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")
        second = BookProviderIdentifier(BookProviderName.GOOGLE, "different")

        assert first != second

    def it_is_not_equal_to_a_value_of_a_different_type():
        identifier = BookProviderIdentifier(BookProviderName.GOOGLE, "abc123")

        assert identifier != "google-books__abc123"
