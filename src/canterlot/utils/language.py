from enum import IntEnum
from functools import cache

import langcodes
from langcodes import standardize_tag, tag_is_valid


class LanguageMatchLevel(IntEnum):
    NONE = 0
    BASE = 1
    FULL = 2


LANGUAGE_MATCH_SUBSCORES: dict[LanguageMatchLevel, float] = {
    LanguageMatchLevel.FULL: 1.0,
    LanguageMatchLevel.BASE: 0.6,
    LanguageMatchLevel.NONE: 0.0,
}


@cache
def normalize_language(lang_str: str) -> str:
    cleaned = lang_str.strip()

    if not cleaned:
        raise ValueError("Language cannot be empty")

    if tag_is_valid(cleaned):
        return standardize_tag(cleaned)

    try:
        return langcodes.find(cleaned).to_tag()
    except LookupError:
        raise ValueError(f"{lang_str!r} is not a valid language code or name") from None


@cache
def _parse_tag(tag: str) -> langcodes.Language | None:
    try:
        return langcodes.get(tag)
    except (LookupError, ValueError):
        return None


def language_match_level(candidate_lang: str, preferred_lang: str) -> LanguageMatchLevel:
    """Compare two language tags, treating a region-less preference as matching any region.

    "pt-BR" only fully matches "pt-BR" (a differently-regioned "pt-PT" is a base-only match),
    but "en" fully matches "en-US", "en-GB", etc. since the preference never asked for a region.
    """
    if candidate_lang == preferred_lang:
        return LanguageMatchLevel.FULL

    candidate_tag = _parse_tag(candidate_lang)
    preferred_tag = _parse_tag(preferred_lang)

    if candidate_tag is None or preferred_tag is None:
        return LanguageMatchLevel.NONE

    if candidate_tag.language != preferred_tag.language:
        return LanguageMatchLevel.NONE

    if not preferred_tag.territory or preferred_tag.territory == candidate_tag.territory:
        return LanguageMatchLevel.FULL

    return LanguageMatchLevel.BASE


def best_language_match(candidate_languages: list[str], preferred_languages: list[str]) -> LanguageMatchLevel:
    if not candidate_languages or not preferred_languages:
        return LanguageMatchLevel.NONE

    return max(
        (language_match_level(c, p) for c in candidate_languages for p in preferred_languages),
        key=lambda level: level.value,
        default=LanguageMatchLevel.NONE,
    )
