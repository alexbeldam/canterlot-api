import asyncio

from canterlot.repositories import DatabaseRepository
from canterlot.utils import get_logger

logger = get_logger(__name__)


class HealthService:
    def __init__(self, database_repos: list[DatabaseRepository]):
        self.__database_repos = database_repos

    async def check(self) -> bool:
        outcomes = await asyncio.gather(
            *(repo.ping() for repo in self.__database_repos),
            return_exceptions=True,
        )
        failures = {
            repo.name: f"{type(outcome).__name__}: {outcome}"
            for repo, outcome in zip(self.__database_repos, outcomes, strict=True)
            if isinstance(outcome, BaseException)
        }
        healthy = not failures

        log = logger.bind(
            dependency_count=len(self.__database_repos),
            failures=failures,
            healthy=healthy,
        )
        if healthy:
            log.debug("Health check passed")
        else:
            log.warning("Health check failed: a dependency is unreachable")

        return healthy
