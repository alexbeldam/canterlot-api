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

from canterlot.hoodie import HoodiePollingConfig, PollingPolicy, init_hoodie
from canterlot.hoodie.testing import delete_all_entities, registered_entities


def current_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


DB_NAME = f"canterlot_integration_test_{current_worker_id()}"


def _shared_state_file(run_uid: str) -> pathlib.Path:
    # OS temp dir (not pytest's own tmp machinery) so both worker fixtures and the controller's
    # pytest_sessionfinish hook can reach it, keyed by run so concurrent runs never share a container.
    return pathlib.Path(tempfile.gettempdir()) / f"canterlot_xdist_mongo_container_{run_uid}.json"


def _shared_lock_file(run_uid: str) -> pathlib.Path:
    return pathlib.Path(tempfile.gettempdir()) / f"canterlot_xdist_mongo_container_{run_uid}.lock"


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


def cleanup_shared_mongo_container(run_uid: str) -> None:
    state_file = _shared_state_file(run_uid)
    if not state_file.is_file():
        return

    state = json.loads(state_file.read_text())
    subprocess.run(["docker", "rm", "-f", state["container_id"]], capture_output=True, check=False)
    state_file.unlink(missing_ok=True)
    _shared_lock_file(run_uid).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[tuple[str, int]]:
    if current_worker_id() == "master":
        container = _new_mongodb_container()
        with container:
            yield container.get_container_host_ip(), container.get_exposed_port(27017)
        return

    run_uid = os.environ["PYTEST_XDIST_TESTRUNUID"]
    state_file = _shared_state_file(run_uid)

    with FileLock(str(_shared_lock_file(run_uid))):
        state: dict[str, Any] | None = json.loads(state_file.read_text()) if state_file.is_file() else None

        if state is None or not _is_container_running(state["container_id"]):
            container = _new_mongodb_container()
            container.start()
            state = {
                "container_id": container.get_container_id(),
                "host": container.get_container_host_ip(),
                "port": container.get_exposed_port(27017),
            }
            state_file.write_text(json.dumps(state))

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
        await client.drop_database(DB_NAME)
        # BeanieCatalogRepository.find_page_by_club_id's free-text/fuzzy path runs a real
        # $search against the books_search Atlas Search index, so this tier needs it built too.
        await init_hoodie(client[DB_NAME], polling=FAST_HOODIE_POLLING)
        yield client
    finally:
        await client.drop_database(DB_NAME)
        await client.close()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def init_hoodied_beanie(hoodie_client: AsyncMongoClient) -> AsyncIterator[None]:
    # Entities stay bound to whichever tier initialized last on this worker.
    bound_database = next(iter(registered_entities())).get_pymongo_collection().database.name
    if bound_database != DB_NAME:
        await init_hoodie(hoodie_client[DB_NAME], polling=FAST_HOODIE_POLLING)
    yield
    await delete_all_entities()
