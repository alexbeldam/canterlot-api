from unittest.mock import AsyncMock

from canterlot.repositories import DatabaseRepository
from canterlot.services.health import HealthService


def _repo(*, ok: bool) -> AsyncMock:
    repo = AsyncMock(spec=DatabaseRepository)
    repo.ping.return_value = ok
    return repo


def describe_check():
    async def it_reports_healthy_when_every_dependency_is_reachable():
        service = HealthService([_repo(ok=True), _repo(ok=True), _repo(ok=True)])

        assert await service.check() is True

    async def it_reports_unhealthy_when_the_first_entry_is_unreachable():
        service = HealthService([_repo(ok=False), _repo(ok=True)])

        assert await service.check() is False

    async def it_reports_unhealthy_when_the_last_entry_is_unreachable():
        service = HealthService([_repo(ok=True), _repo(ok=False)])

        assert await service.check() is False
