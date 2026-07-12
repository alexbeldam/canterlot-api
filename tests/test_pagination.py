from canterlot.pagination import Page


def _page(**overrides) -> Page:
    defaults = {"items": [], "total_items": 0, "current_page": 1, "page_size": 20}
    return Page(**{**defaults, **overrides})


def describe_total_pages():
    def it_rounds_up_a_partial_final_page():
        page = _page(total_items=21, page_size=20)

        assert page.total_pages == 2

    def it_returns_zero_when_there_are_no_items():
        page = _page(total_items=0, page_size=20)

        assert page.total_pages == 0

    def it_divides_evenly_when_total_items_is_a_multiple_of_page_size():
        page = _page(total_items=40, page_size=20)

        assert page.total_pages == 2


def describe_has_next():
    def it_is_true_when_the_current_page_is_before_the_last_page():
        page = _page(total_items=40, current_page=1, page_size=20)

        assert page.has_next is True

    def it_is_false_on_the_last_page():
        page = _page(total_items=40, current_page=2, page_size=20)

        assert page.has_next is False


def describe_has_previous():
    def it_is_false_on_the_first_page():
        page = _page(current_page=1)

        assert page.has_previous is False

    def it_is_true_after_the_first_page():
        page = _page(current_page=2)

        assert page.has_previous is True


def describe_of():
    def it_slices_the_first_page():
        result = Page.of(list(range(25)), page=1, limit=10)

        assert result.items == list(range(10))
        assert result.total_items == 25
        assert result.current_page == 1
        assert result.total_pages == 3

    def it_slices_a_middle_page():
        result = Page.of(list(range(25)), page=2, limit=10)

        assert result.items == list(range(10, 20))

    def it_slices_a_partial_final_page():
        result = Page.of(list(range(25)), page=3, limit=10)

        assert result.items == list(range(20, 25))

    def it_returns_an_empty_page_past_the_end():
        result = Page.of(list(range(5)), page=5, limit=10)

        assert result.items == []
        assert result.total_items == 5

    def it_handles_an_empty_input_list():
        result = Page.of([], page=1, limit=10)

        assert result.items == []
        assert result.total_items == 0
        assert result.total_pages == 0


def describe_map():
    def it_transforms_items_while_preserving_pagination_metadata():
        page = _page(items=[1, 2, 3], total_items=3, current_page=1, page_size=20)

        mapped = page.map(str)

        assert mapped.items == ["1", "2", "3"]
        assert mapped.total_items == 3
        assert mapped.current_page == 1
        assert mapped.page_size == 20

    def it_maps_an_empty_page_to_an_empty_page():
        page = _page()

        mapped = page.map(str)

        assert mapped.items == []
