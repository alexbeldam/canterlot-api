import pathlib
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from beanie import init_beanie
from pymongo import AsyncMongoClient
from testcontainers.mongodb import MongoDbContainer

from canterlot.models import BEANIE_DOCUMENT_MODELS

_THIS_DIR = pathlib.Path(__file__).parent
_DB_NAME = "canterlot_integration_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def mongodb_container() -> Iterator[MongoDbContainer]:
    with MongoDbContainer("mongo:6.0") as container:
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _beanie_client(mongodb_container: MongoDbContainer) -> AsyncIterator[AsyncMongoClient]:
    client: AsyncMongoClient = AsyncMongoClient(mongodb_container.get_connection_url())
    try:
        await init_beanie(database=client[_DB_NAME], document_models=BEANIE_DOCUMENT_MODELS)
        yield client
    finally:
        await client.drop_database(_DB_NAME)
        await client.close()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _initialized_beanie(_beanie_client: AsyncMongoClient) -> AsyncIterator[None]:
    yield
    for model in BEANIE_DOCUMENT_MODELS:
        await model.delete_all()
