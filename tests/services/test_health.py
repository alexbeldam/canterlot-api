from unittest.mock import AsyncMock

from structlog.testing import capture_logs

from canterlot.repositories import DatabaseRepository
from canterlot.services.health import HealthService


def _repo(*, ok: bool, name: str = "dependency") -> AsyncMock:
    repo = AsyncMock(spec=DatabaseRepository)
    repo.name = name
    if not ok:
        repo.ping.side_effect = ConnectionError("connection refused")
    return repo


def describe_check():
    async def it_reports_healthy_when_every_dependency_is_reachable():
        service = HealthService([_repo(ok=True), _repo(ok=True), _repo(ok=True)])

        assert await service.check() is True

    async def it_reports_unhealthy_when_the_first_entry_is_unreachable():
        service = HealthService([_repo(ok=False), _repo(ok=True)])

        assert await service.check() is False

    async def it_logs_which_dependencies_failed_and_why():
        service = HealthService(
            [
                _repo(ok=True, name="mongodb-atlas"),
                _repo(ok=False, name="redis"),
            ]
        )

        with capture_logs() as logs:
            await service.check()

        assert logs[0]["failures"] == {"redis": "ConnectionError: connection refused"}

    async def it_reports_unhealthy_when_the_last_entry_is_unreachable():
        service = HealthService([_repo(ok=True), _repo(ok=False)])

        assert await service.check() is False
