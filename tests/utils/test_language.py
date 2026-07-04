from canterlot.utils.language import (
    LANGUAGE_MATCH_SUBSCORES,
    LanguageMatchLevel,
    best_language_match,
    language_match_level,
)


def describe_language_match_level():
    def it_treats_an_identical_tag_as_a_full_match():
        assert language_match_level("en", "en") is LanguageMatchLevel.FULL

    def it_treats_a_region_less_preference_as_matching_any_region():
        assert language_match_level("en-US", "en") is LanguageMatchLevel.FULL
        assert language_match_level("en-GB", "en") is LanguageMatchLevel.FULL

    def it_treats_a_differently_regioned_match_as_base_only():
        assert language_match_level("pt-PT", "pt-BR") is LanguageMatchLevel.BASE

    def it_treats_a_different_base_language_as_no_match():
        assert language_match_level("es", "en") is LanguageMatchLevel.NONE

    def it_treats_an_unparsable_candidate_tag_as_no_match():
        assert language_match_level("???", "en") is LanguageMatchLevel.NONE

    def it_treats_an_unparsable_preferred_tag_as_no_match():
        assert language_match_level("en", "???") is LanguageMatchLevel.NONE


def describe_best_language_match():
    def it_returns_none_when_either_list_is_empty():
        assert best_language_match([], ["en"]) is LanguageMatchLevel.NONE
        assert best_language_match(["en"], []) is LanguageMatchLevel.NONE

    def it_returns_the_best_match_across_every_pairing():
        assert best_language_match(["es", "en-US"], ["en"]) is LanguageMatchLevel.FULL

    def it_returns_none_when_nothing_matches():
        assert best_language_match(["es", "fr"], ["en"]) is LanguageMatchLevel.NONE


def describe_language_match_subscores():
    def it_defines_a_strictly_descending_scale():
        assert LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.FULL] > LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.BASE]
        assert LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.BASE] > LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.NONE]

    def it_scores_a_full_match_as_one():
        assert LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.FULL] == 1.0

    def it_scores_no_match_as_zero():
        assert LANGUAGE_MATCH_SUBSCORES[LanguageMatchLevel.NONE] == 0.0
