import pytest
from pydantic import ValidationError

from tools.factories import ReadBookFactory


def describe_rating_validation():
    @pytest.mark.parametrize("rating", [0.5, 1.0, 2.5, 5.0])
    def it_accepts_half_step_ratings_within_bounds(rating: float):
        document = ReadBookFactory.build(rating=rating)
        assert document.rating == rating

    def it_defaults_to_no_rating():
        document = ReadBookFactory.build(rating=None)
        assert document.rating is None

    @pytest.mark.parametrize("rating", [0.0, 0.4, 5.5, 10.0])
    def it_rejects_ratings_outside_the_0_5_to_5_bounds(rating: float):
        with pytest.raises(ValidationError, match="rating"):
            ReadBookFactory.build(rating=rating)

    @pytest.mark.parametrize("rating", [0.6, 1.2, 3.3])
    def it_rejects_ratings_not_on_a_half_step(rating: float):
        with pytest.raises(ValidationError, match="rating"):
            ReadBookFactory.build(rating=rating)
