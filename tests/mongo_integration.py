import json
import os
import pathlib
import subprocess
import tempfile
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from filelock import FileLock
from pymongo import AsyncMongoClient
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HealthcheckWaitStrategy

from canterlot.hoodie import HoodiePollingConfig, PollingPolicy, delete_all_entities, init_hoodie


def current_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


DB_NAME = f"canterlot_integration_test_{current_worker_id()}"

# A fixed OS-temp-dir location (not pytest's own tmp machinery) so it's reachable both from
# worker-process fixtures and from the controller process's pytest_sessionfinish hook.
_SHARED_STATE_FILE = pathlib.Path(tempfile.gettempdir()) / "canterlot_xdist_mongo_container.json"
_SHARED_LOCK_FILE = pathlib.Path(tempfile.gettempdir()) / "canterlot_xdist_mongo_container.lock"

# Polling returns the moment the index settles, so a fast machine never pays for the budget. The
# budget (about 5 minutes per wait) only has to outlast the slowest machine's mongot, so the suite's
# outcome never depends on host speed.
SETTLE_POLICY = PollingPolicy(max_attempts=600, initial_interval=0.02, backoff_multiplier=1.5, max_interval=0.5)
FAST_HOODIE_POLLING = HoodiePollingConfig(search_sync=SETTLE_POLICY, index_build=SETTLE_POLICY)

_INTEGRATION_DIRS = (
    pathlib.Path(__file__).parent / "repositories",
    pathlib.Path(__file__).parent / "hoodie",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if any(directory in item.path.parents for directory in _INTEGRATION_DIRS):
            item.add_marker(pytest.mark.integration)


def _new_mongodb_container() -> DockerContainer:
    # A raw container, not MongoDbContainer, since that helper wraps community mongo's env-var scheme,
    # not mongodb-atlas-local's.
    return (
        DockerContainer("mongodb/mongodb-atlas-local:8.0")
        .with_exposed_ports(27017)
        .waiting_for(HealthcheckWaitStrategy())
    )


def _is_container_running(container_id: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def cleanup_shared_mongo_container() -> None:
    if not _SHARED_STATE_FILE.is_file():
        return

    state = json.loads(_SHARED_STATE_FILE.read_text())
    subprocess.run(["docker", "rm", "-f", state["container_id"]], capture_output=True, check=False)
    _SHARED_STATE_FILE.unlink(missing_ok=True)
    _SHARED_LOCK_FILE.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[tuple[str, int]]:
    if current_worker_id() == "master":
        container = _new_mongodb_container()
        with container:
            yield container.get_container_host_ip(), container.get_exposed_port(27017)
        return

    with FileLock(str(_SHARED_LOCK_FILE)):
        state: dict[str, Any] | None = (
            json.loads(_SHARED_STATE_FILE.read_text()) if _SHARED_STATE_FILE.is_file() else None
        )

        if state is None or not _is_container_running(state["container_id"]):
            container = _new_mongodb_container()
            container.start()
            state = {
                "container_id": container.get_container_id(),
                "host": container.get_container_host_ip(),
                "port": container.get_exposed_port(27017),
            }
            _SHARED_STATE_FILE.write_text(json.dumps(state))

    host: str = state["host"]
    port: int = state["port"]
    yield host, port


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def hoodie_client(mongodb_container: tuple[str, int]) -> AsyncIterator[AsyncMongoClient]:
    host, port = mongodb_container
    # directConnection=True: the node advertises itself as "localhost:27017", not the Docker-mapped port.
    url = f"mongodb://{host}:{port}/?directConnection=true"

    client: AsyncMongoClient = AsyncMongoClient(url, tz_aware=True)
    try:
        # BeanieCatalogRepository.find_page_by_club_id's free-text/fuzzy path runs a real
        # $search against the books_search Atlas Search index, so this tier needs it built too.
        await init_hoodie(client[DB_NAME], polling=FAST_HOODIE_POLLING)
        yield client
    finally:
        await client.drop_database(DB_NAME)
        await client.close()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def init_hoodied_beanie(hoodie_client: AsyncMongoClient) -> AsyncIterator[None]:  # noqa: ARG001
    yield
    await delete_all_entities()
