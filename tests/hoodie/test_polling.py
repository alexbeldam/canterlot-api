import asyncio

import pytest

from canterlot.hoodie.polling import PollCoalescer, PollingPolicy, poll_until


def describe_polling_policy_interval_for() -> None:
    def it_does_not_cap_the_interval_when_no_max_interval_is_configured() -> None:
        policy = PollingPolicy(max_attempts=5, initial_interval=1.0, backoff_multiplier=2.0)

        assert policy.interval_for(4) == 8.0


def describe_poll_until() -> None:
    @pytest.mark.asyncio(loop_scope="session")
    async def it_returns_true_as_soon_as_settled_reports_success() -> None:
        attempts = 0

        async def settled() -> bool:
            nonlocal attempts
            attempts += 1
            return True

        result = await poll_until(
            settled,
            policy=PollingPolicy(max_attempts=3, initial_interval=0.001),
            on_retry=lambda _attempt: None,
        )

        assert result is True
        assert attempts == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def it_returns_false_after_exhausting_every_attempt() -> None:
        retries: list[int] = []

        async def never_settles() -> bool:
            return False

        result = await poll_until(
            never_settles,
            policy=PollingPolicy(max_attempts=3, initial_interval=0.001),
            on_retry=retries.append,
        )

        assert result is False
        assert retries == [1, 2]


def describe_poll_coalescer() -> None:
    @pytest.mark.asyncio(loop_scope="session")
    async def it_shares_one_execution_between_concurrent_callers_on_the_same_key() -> None:
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def probe() -> str:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "done"

        coalescer: PollCoalescer[str, str] = PollCoalescer()

        first = asyncio.create_task(coalescer.run("key", probe))
        await started.wait()
        second = asyncio.create_task(coalescer.run("key", probe))

        release.set()
        results = await asyncio.gather(first, second)

        assert results == ["done", "done"]
        assert calls == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def it_runs_independent_keys_independently() -> None:
        calls: list[str] = []

        async def probe(key: str) -> str:
            calls.append(key)
            return key

        coalescer: PollCoalescer[str, str] = PollCoalescer()

        results = await asyncio.gather(
            coalescer.run("a", lambda: probe("a")),
            coalescer.run("b", lambda: probe("b")),
        )

        assert sorted(results) == ["a", "b"]
        assert sorted(calls) == ["a", "b"]

    @pytest.mark.asyncio(loop_scope="session")
    async def it_propagates_an_exception_to_every_waiter_sharing_the_failed_key() -> None:
        class _Boom(Exception):
            pass

        started = asyncio.Event()
        release = asyncio.Event()

        async def probe() -> None:
            started.set()
            await release.wait()
            raise _Boom

        coalescer: PollCoalescer[str, None] = PollCoalescer()

        first = asyncio.create_task(coalescer.run("key", probe))
        await started.wait()
        second = asyncio.create_task(coalescer.run("key", probe))

        release.set()
        with pytest.raises(_Boom):
            await first
        with pytest.raises(_Boom):
            await second

    @pytest.mark.asyncio(loop_scope="session")
    async def it_starts_a_fresh_probe_for_a_call_made_after_the_keys_previous_probe_settled() -> None:
        calls = 0

        async def probe() -> int:
            nonlocal calls
            calls += 1
            return calls

        coalescer: PollCoalescer[str, int] = PollCoalescer()

        first_result = await coalescer.run("key", probe)
        second_result = await coalescer.run("key", probe)

        assert first_result == 1
        assert second_result == 2
        assert calls == 2
