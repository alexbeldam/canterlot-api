import random
from collections import defaultdict
from datetime import datetime

from beanie import PydanticObjectId

from canterlot.models import BookModel, CatalogEntryModel, RatingStats
from canterlot.types import LanguageStr

AGE_WEIGHT_FLOOR = 1
PREFERRED_LANGUAGE_BOOST = 2.0
RATING_BOOST_MIN = 0.6
RATING_BOOST_MAX = 1.5
RATING_BOOST_MIN_COUNT = 3
RATING_SCALE_MIN = 0.5
RATING_SCALE_MAX = 5.0
FAMILIARITY_FLOOR = 0.2
POOL_MAX = 5


def _age_weight(suggested_at: datetime, now: datetime) -> int:
    days_since_suggested = (now - suggested_at).days
    return max(AGE_WEIGHT_FLOOR, days_since_suggested)


def _base_weights(entries: list[CatalogEntryModel], now: datetime) -> dict[PydanticObjectId, float]:
    groups: dict[PydanticObjectId, list[CatalogEntryModel]] = defaultdict(list)
    for entry in entries:
        groups[entry.suggested_by].append(entry)

    share_per_suggester = 1 / len(groups) if groups else 0.0
    weights: dict[PydanticObjectId, float] = {}

    for group_entries in groups.values():
        age_weights = {entry.book_id: _age_weight(entry.suggested_at, now) for entry in group_entries}
        group_total = sum(age_weights.values())

        for entry in group_entries:
            weights[entry.book_id] = share_per_suggester * (age_weights[entry.book_id] / group_total)

    return weights


def _language_boost(book: BookModel, preferred_languages: list[LanguageStr]) -> float:
    if not preferred_languages:
        return 1.0
    if set(book.languages) & set(preferred_languages):
        return PREFERRED_LANGUAGE_BOOST
    return 1.0


def _familiarity_multiplier(readers_count: int, current_member_count: int) -> float:
    if current_member_count <= 0:
        return 1.0

    familiarity_fraction = readers_count / current_member_count
    return max(FAMILIARITY_FLOOR, 1 - familiarity_fraction * (1 - FAMILIARITY_FLOOR))


def _rating_boost(rating_stats: RatingStats | None) -> float:
    if rating_stats is None or rating_stats.average_rating is None:
        return 1.0
    if rating_stats.rating_count < RATING_BOOST_MIN_COUNT:
        return 1.0

    scale = (rating_stats.average_rating - RATING_SCALE_MIN) / (RATING_SCALE_MAX - RATING_SCALE_MIN)
    return RATING_BOOST_MIN + scale * (RATING_BOOST_MAX - RATING_BOOST_MIN)


def compute_candidate_weights(
    entries: list[CatalogEntryModel],
    preferred_languages: list[LanguageStr],
    familiarity_counts: dict[PydanticObjectId, int],
    current_member_count: int,
    rating_stats_by_book: dict[PydanticObjectId, RatingStats],
    books_by_id: dict[PydanticObjectId, BookModel],
    now: datetime,
) -> dict[PydanticObjectId, float]:
    weights = _base_weights(entries, now)

    for entry in entries:
        book = books_by_id[entry.book_id]
        weights[entry.book_id] *= _language_boost(book, preferred_languages)
        weights[entry.book_id] *= _familiarity_multiplier(
            familiarity_counts.get(entry.book_id, 0),
            current_member_count,
        )
        weights[entry.book_id] *= _rating_boost(rating_stats_by_book.get(entry.book_id))

    return weights


def select_top_n_pool(
    entries: list[CatalogEntryModel],
    weights: dict[PydanticObjectId, float],
    n: int = POOL_MAX,
) -> list[PydanticObjectId]:
    ordered = sorted(entries, key=lambda entry: (-weights[entry.book_id], entry.suggested_at))
    return [entry.book_id for entry in ordered[:n]]


def weighted_random_draw(rng: random.Random, weights: dict[PydanticObjectId, float]) -> PydanticObjectId:
    book_ids = list(weights.keys())
    return rng.choices(book_ids, weights=[weights[book_id] for book_id in book_ids], k=1)[0]
