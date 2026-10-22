import pytest
from pymongo.errors import PyMongoError

from canterlot.models import UserModel
from canterlot.repositories.beanie import BeanieDatabaseRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")


def describe_name():
    async def it_identifies_the_dependency_as_mongodb():
        assert BeanieDatabaseRepository().name == "mongodb"


def describe_ping():
    async def it_succeeds_when_mongo_is_reachable():
        await BeanieDatabaseRepository().ping()

    async def it_raises_when_mongo_is_unreachable(monkeypatch: pytest.MonkeyPatch):
        class _UnreachableDatabase:
            async def command(self, *_args, **_kwargs):
                raise PyMongoError("no route to host")

        class _UnreachableCollection:
            database = _UnreachableDatabase()

        monkeypatch.setattr(UserModel, "get_pymongo_collection", classmethod(lambda _cls: _UnreachableCollection()))

        with pytest.raises(PyMongoError, match="no route to host"):
            await BeanieDatabaseRepository().ping()
