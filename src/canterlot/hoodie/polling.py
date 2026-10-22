import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class PollingPolicy:
    """How a poll loop retries: how many attempts, and how long to sleep between them.

    The sleep before attempt `n + 1` is `initial_interval * backoff_multiplier ** (n - 1)`,
    capped at `max_interval` when one is set.

    :param max_attempts: the total number of checks before giving up.
    :type max_attempts: int
    :param initial_interval: seconds to sleep after the first failed check.
    :type initial_interval: float
    :param backoff_multiplier: growth factor applied to the interval after each failed check.
    :type backoff_multiplier: float
    :param max_interval: upper bound in seconds on the sleep between checks, or None for no cap.
    :type max_interval: float | None
    """

    max_attempts: int
    initial_interval: float
    backoff_multiplier: float = 1.0
    max_interval: float | None = None

    def interval_for(self, attempt: int) -> float:
        interval = self.initial_interval * (self.backoff_multiplier ** (attempt - 1))
        if self.max_interval is not None:
            interval = min(interval, self.max_interval)
        return interval


DEFAULT_SEARCH_SYNC_POLICY = PollingPolicy(
    max_attempts=40,
    initial_interval=0.25,
    backoff_multiplier=1.5,
    max_interval=2.0,
)
DEFAULT_INDEX_BUILD_POLICY = PollingPolicy(
    max_attempts=30,
    initial_interval=1.0,
    backoff_multiplier=1.5,
    max_interval=5.0,
)


class HoodiePollingConfig(BaseModel):
    """Tunable polling intervals for hoodie's search-sync verification and search-index
    build/update readiness checks.

    Passed to `init_hoodie`'s `polling` parameter. The defaults are tuned for real Atlas
    Search's production-grade indexing lag; a caller running against a faster local search
    process (e.g. `mongot` in a test container) can substitute a config with shorter
    intervals.

    :param search_sync: the policy `@synced` writes poll against before returning.
    :type search_sync: PollingPolicy
    :param index_build: the policy search-index build/update readiness checks poll against.
    :type index_build: PollingPolicy
    """

    search_sync: PollingPolicy = Field(default=DEFAULT_SEARCH_SYNC_POLICY)
    index_build: PollingPolicy = Field(default=DEFAULT_INDEX_BUILD_POLICY)

    model_config = ConfigDict(frozen=True)


async def poll_until(
    settled: Callable[[], Awaitable[bool]],
    *,
    policy: PollingPolicy,
    on_retry: Callable[[int], None],
) -> bool:
    for attempt in range(1, policy.max_attempts + 1):
        if await settled():
            return True
        if attempt < policy.max_attempts:
            on_retry(attempt)
            await asyncio.sleep(policy.interval_for(attempt))
    return False


class PollCoalescer[K: Hashable, V]:
    def __init__(self) -> None:
        self._in_flight: dict[K, asyncio.Task[V]] = {}

    async def run(self, key: K, probe: Callable[[], Awaitable[V]]) -> V:
        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.create_task(self._run_and_release(key, probe))
            self._in_flight[key] = task

        return await asyncio.shield(task)

    async def _run_and_release(self, key: K, probe: Callable[[], Awaitable[V]]) -> V:
        try:
            return await probe()
        finally:
            del self._in_flight[key]
