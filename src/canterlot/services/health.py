from canterlot.repositories import DatabaseRepository
from canterlot.utils import get_logger

logger = get_logger(__name__)


class HealthService:
    def __init__(self, database_repos: list[DatabaseRepository]):
        self.__database_repos = database_repos

    async def check(self) -> bool:
        healthy = all([await repo.ping() for repo in self.__database_repos])

        log = logger.bind(dependency_count=len(self.__database_repos), healthy=healthy)
        if healthy:
            log.debug("Health check passed")
        else:
            log.warn("Health check failed: a dependency is unreachable")

        return healthy
