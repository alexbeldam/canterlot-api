from canterlot.utils.scoring import redistribute_weights


def describe_redistribute_weights():
    def it_returns_weights_unchanged_when_they_already_sum_to_one():
        assert redistribute_weights({"title": 0.5, "author": 0.3, "language": 0.2}) == {
            "title": 0.5,
            "author": 0.3,
            "language": 0.2,
        }

    def it_scales_up_a_subset_of_weights_to_sum_to_one():
        result = redistribute_weights({"title": 0.5, "author": 0.3})
        assert result["title"] == 0.5 / 0.8
        assert result["author"] == 0.3 / 0.8
        assert sum(result.values()) == 1.0

    def it_returns_a_single_weight_as_one():
        assert redistribute_weights({"title": 0.5}) == {"title": 1.0}

    def it_returns_zeros_for_an_empty_weights_dict():
        assert redistribute_weights({}) == {}

    def it_returns_zeros_when_every_weight_is_zero():
        assert redistribute_weights({"title": 0.0, "author": 0.0}) == {"title": 0.0, "author": 0.0}
