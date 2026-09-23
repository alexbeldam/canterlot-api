import random
from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId

from canterlot.models.read_book import RatingStats
from canterlot.utils.weighting import (
    compute_candidate_weights,
    select_top_n_pool,
    weighted_random_draw,
)
from tools.factories import BookFactory, CatalogEntryFactory

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def _entry(book_id: PydanticObjectId, suggested_by: PydanticObjectId, days_ago: int):
    return CatalogEntryFactory.build(
        book_id=book_id,
        suggested_by=suggested_by,
        suggested_at=NOW - timedelta(days=days_ago),
    )


def describe_compute_candidate_weights():
    def it_normalizes_weight_equally_across_distinct_suggesters():
        suggester_a, suggester_b = PydanticObjectId(), PydanticObjectId()
        book_a1 = PydanticObjectId()
        book_b1, book_b2 = PydanticObjectId(), PydanticObjectId()
        entries = [
            _entry(book_a1, suggester_a, 10),
            _entry(book_b1, suggester_b, 1),
            _entry(book_b2, suggester_b, 9),
        ]
        books_by_id = {e.book_id: BookFactory.build(languages=[]) for e in entries}

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=[],
            familiarity_counts={},
            current_member_count=4,
            rating_stats_by_book={},
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[book_a1] == pytest.approx(0.5)
        assert weights[book_b1] == pytest.approx(0.05)
        assert weights[book_b2] == pytest.approx(0.45)

    def it_applies_a_minimum_age_weight_of_one_for_a_book_suggested_today():
        suggester = PydanticObjectId()
        fresh_book, older_book = PydanticObjectId(), PydanticObjectId()
        entries = [
            _entry(fresh_book, suggester, 0),
            _entry(older_book, suggester, 3),
        ]
        books_by_id = {e.book_id: BookFactory.build(languages=[]) for e in entries}

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=[],
            familiarity_counts={},
            current_member_count=4,
            rating_stats_by_book={},
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[fresh_book] == pytest.approx(0.25)
        assert weights[older_book] == pytest.approx(0.75)

    def it_applies_the_preferred_language_boost():
        suggester_a, suggester_b = PydanticObjectId(), PydanticObjectId()
        boosted_book, plain_book = PydanticObjectId(), PydanticObjectId()
        entries = [
            _entry(boosted_book, suggester_a, 5),
            _entry(plain_book, suggester_b, 5),
        ]
        books_by_id = {
            boosted_book: BookFactory.build(languages=["en"]),
            plain_book: BookFactory.build(languages=["fr"]),
        }

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=["en"],
            familiarity_counts={},
            current_member_count=4,
            rating_stats_by_book={},
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[boosted_book] == pytest.approx(1.0)
        assert weights[plain_book] == pytest.approx(0.5)

    def it_applies_the_familiarity_penalty_with_a_floor_of_0_2():
        suggester_a, suggester_b = PydanticObjectId(), PydanticObjectId()
        familiar_book, unknown_book = PydanticObjectId(), PydanticObjectId()
        entries = [
            _entry(familiar_book, suggester_a, 5),
            _entry(unknown_book, suggester_b, 5),
        ]
        books_by_id = {e.book_id: BookFactory.build(languages=[]) for e in entries}

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=[],
            familiarity_counts={familiar_book: 4},
            current_member_count=4,
            rating_stats_by_book={},
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[familiar_book] == pytest.approx(0.1)
        assert weights[unknown_book] == pytest.approx(0.5)

    def it_applies_the_rating_boost_only_once_a_book_has_at_least_three_ratings():
        suggester_a, suggester_b = PydanticObjectId(), PydanticObjectId()
        well_rated_book, under_rated_book = PydanticObjectId(), PydanticObjectId()
        entries = [
            _entry(well_rated_book, suggester_a, 5),
            _entry(under_rated_book, suggester_b, 5),
        ]
        books_by_id = {e.book_id: BookFactory.build(languages=[]) for e in entries}

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=[],
            familiarity_counts={},
            current_member_count=4,
            rating_stats_by_book={
                well_rated_book: RatingStats(average_rating=5.0, rating_count=3),
                under_rated_book: RatingStats(average_rating=5.0, rating_count=2),
            },
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[well_rated_book] == pytest.approx(0.75)
        assert weights[under_rated_book] == pytest.approx(0.5)

    def it_maps_the_lowest_qualifying_average_to_the_minimum_rating_boost():
        suggester = PydanticObjectId()
        book = PydanticObjectId()
        entries = [_entry(book, suggester, 5)]
        books_by_id = {book: BookFactory.build(languages=[])}

        weights = compute_candidate_weights(
            entries=entries,
            preferred_languages=[],
            familiarity_counts={},
            current_member_count=4,
            rating_stats_by_book={book: RatingStats(average_rating=0.5, rating_count=3)},
            books_by_id=books_by_id,
            now=NOW,
        )

        assert weights[book] == pytest.approx(0.6)


def describe_select_top_n_pool():
    def it_selects_the_top_n_entries_by_weight():
        entries = [_entry(PydanticObjectId(), PydanticObjectId(), 1) for _ in range(6)]
        weights = {entry.book_id: float(i) for i, entry in enumerate(entries)}

        pool = select_top_n_pool(entries, weights, n=5)

        expected = [entry.book_id for entry in sorted(entries, key=lambda e: -weights[e.book_id])][:5]
        assert pool == expected
        assert len(pool) == 5

    def it_breaks_ties_by_earliest_suggestion():
        suggester = PydanticObjectId()
        earlier = _entry(PydanticObjectId(), suggester, 10)
        later = _entry(PydanticObjectId(), suggester, 1)
        weights = {earlier.book_id: 1.0, later.book_id: 1.0}

        pool = select_top_n_pool([earlier, later], weights, n=1)

        assert pool == [earlier.book_id]


def describe_weighted_random_draw():
    def it_only_ever_draws_a_book_with_nonzero_weight():
        winner, loser = PydanticObjectId(), PydanticObjectId()
        weights = {winner: 1.0, loser: 0.0}

        drawn = weighted_random_draw(random.Random(42), weights)

        assert drawn == winner

    def it_draws_the_only_candidate_when_a_single_entry_remains():
        only = PydanticObjectId()

        drawn = weighted_random_draw(random.Random(1), {only: 0.37})

        assert drawn == only
