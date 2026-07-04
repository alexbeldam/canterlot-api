import asyncio

import pytest

from canterlot.utils.mirror import MirrorPool


def describe_mirror_pool_construction():
    def it_raises_value_error_when_given_no_mirrors():
        with pytest.raises(ValueError, match="at least one mirror"):
            MirrorPool([])

    def it_exposes_the_first_mirror_as_preferred():
        pool = MirrorPool(["a", "b", "c"])
        assert pool.preferred == "a"


def describe_execute():
    async def it_returns_the_result_from_the_preferred_mirror_when_it_succeeds():
        pool = MirrorPool(["a", "b"])

        async def op(mirror: str) -> str:
            return f"result-from-{mirror}"

        assert await pool.execute(op) == "result-from-a"
        assert pool.preferred == "a"

    async def it_forwards_positional_and_keyword_arguments_to_the_operation():
        pool = MirrorPool(["a"])

        async def op(_mirror: str, value: int, *, multiplier: int) -> int:
            return value * multiplier

        assert await pool.execute(op, 21, multiplier=2) == 42

    async def it_falls_back_to_racing_the_pool_when_the_preferred_mirror_fails():
        pool = MirrorPool(["a", "b", "c"])

        async def op(mirror: str) -> str:
            if mirror == "a":
                raise RuntimeError("preferred is down")
            if mirror == "b":
                await asyncio.sleep(0.05)
                return "from-b"
            return "from-c"

        assert await pool.execute(op) == "from-c"
        assert pool.preferred == "c"

    async def it_promotes_the_winning_mirror_to_preferred_for_subsequent_calls():
        pool = MirrorPool(["a", "b"])

        async def failing_a_op(mirror: str) -> str:
            if mirror == "a":
                raise RuntimeError("always down")
            return "from-b"

        await pool.execute(failing_a_op)
        assert pool.preferred == "b"

        async def op(mirror: str) -> str:
            return f"from-{mirror}"

        assert await pool.execute(op) == "from-b"

    async def it_raises_an_exception_group_when_every_mirror_fails():
        pool = MirrorPool(["a", "b"])

        async def op(mirror: str) -> str:
            raise RuntimeError(f"{mirror} is down")

        with pytest.raises(ExceptionGroup) as exc_info:
            await pool.execute(op)

        assert len(exc_info.value.exceptions) == 2

    async def it_propagates_cancellation_without_racing_other_mirrors() -> None:
        pool = MirrorPool(["a", "b"])
        attempted: list[str] = []

        async def op(mirror: str) -> str:
            attempted.append(mirror)
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await pool.execute(op)

        assert attempted == ["a"]
