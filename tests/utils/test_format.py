import pytest

from canterlot.utils.format import similarity_ratio


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
