import pytest
from pydantic import TypeAdapter, ValidationError

from canterlot.utils.format import (
    HttpsUrl,
    ISBN10Str,
    ISBN13Str,
    ISBNStr,
    LanguageStr,
    NonEmptyStr,
    NormalizedEmailStr,
    make_slug,
    similarity_ratio,
    split_isbn,
)

language_adapter: TypeAdapter[LanguageStr] = TypeAdapter(LanguageStr)
isbn_adapter: TypeAdapter[ISBNStr] = TypeAdapter(ISBNStr)
isbn10_adapter: TypeAdapter[ISBN10Str] = TypeAdapter(ISBN10Str)
isbn13_adapter: TypeAdapter[ISBN13Str] = TypeAdapter(ISBN13Str)
non_empty_adapter: TypeAdapter[NonEmptyStr] = TypeAdapter(NonEmptyStr)
email_adapter: TypeAdapter[NormalizedEmailStr] = TypeAdapter(NormalizedEmailStr)
https_url_adapter: TypeAdapter[HttpsUrl] = TypeAdapter(HttpsUrl)


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


def describe_split_isbn():
    def it_splits_an_isbn10_correctly():
        isbn10, isbn13 = split_isbn("0_306_40615_x")
        assert isbn10 == "030640615X"
        assert isbn13 is None

    def it_splits_an_isbn13_correctly():
        isbn10, isbn13 = split_isbn("978-3-16-148410-0")
        assert isbn10 is None
        assert isbn13 == "9783161484100"

    def it_validates_and_fails_on_bad_input():
        with pytest.raises(ValidationError):
            split_isbn("not-an-isbn")


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


def describe_similarity_ratio():
    def it_returns_one_for_identical_strings():
        assert similarity_ratio("The Hobbit", "The Hobbit") == 1.0

    def it_is_case_and_whitespace_insensitive():
        assert similarity_ratio("  The Hobbit  ", "the hobbit") == 1.0

    @pytest.mark.parametrize("a, b", [("", "something"), ("something", ""), ("", "")])
    def it_returns_zero_when_either_input_is_empty(a: str, b: str):
        assert similarity_ratio(a, b) == 0.0

    def it_returns_a_low_score_for_dissimilar_strings():
        assert similarity_ratio("The Hobbit", "Completely Different Title") < 0.5


def describe_make_slug():
    async def it_returns_the_plain_slug_when_it_is_not_a_duplicate():
        async def never_taken(_slug: str) -> bool:
            return False

        slug = await make_slug("The Canterlot Archives", never_taken)

        assert slug == "the-canterlot-archives"

    async def it_appends_a_random_suffix_when_the_slug_is_already_taken() -> None:
        calls: list[str] = []

        async def taken_once(candidate: str) -> bool:
            calls.append(candidate)
            return len(calls) == 1

        slug = await make_slug("The Canterlot Archives", taken_once)

        assert len(calls) == 2
        assert calls[0] == "the-canterlot-archives"
        assert slug.startswith("the-canterlot-archives-")
        assert slug != calls[0]

    async def it_keeps_retrying_with_fresh_suffixes_until_one_is_free() -> None:
        calls: list[str] = []

        async def taken_twice(candidate: str) -> bool:
            calls.append(candidate)
            return len(calls) <= 2

        slug = await make_slug("The Canterlot Archives", taken_twice)

        assert len(calls) == 3
        assert slug not in calls[:2]

    async def it_respects_the_configured_max_length_and_suffix_length():
        async def never_taken(_slug: str) -> bool:
            return False

        slug = await make_slug("A" * 100, never_taken, max_length=10, suffix_length=3)

        assert len(slug) <= 10
