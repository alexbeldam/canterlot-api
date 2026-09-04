from canterlot.utils.slugs import make_slug, make_username


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


def describe_make_username():
    async def it_returns_an_underscore_separated_username_when_it_is_not_a_duplicate():
        async def never_taken(_username: str) -> bool:
            return False

        username = await make_username("Twilight Sparkle", never_taken)

        assert username == "twilight_sparkle"

    async def it_appends_a_random_suffix_with_underscores_when_taken() -> None:
        calls: list[str] = []

        async def taken_once(candidate: str) -> bool:
            calls.append(candidate)
            return len(calls) == 1

        username = await make_username("Twilight Sparkle", taken_once)

        assert calls[0] == "twilight_sparkle"
        assert username.startswith("twilight_sparkle_")
        assert "-" not in username
