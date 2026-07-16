import pytest
from pymongo.errors import PyMongoError

from canterlot.models import UserModel
from canterlot.repositories.beanie import BeanieDatabaseRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")


def describe_ping():
    async def it_returns_true_when_mongo_is_reachable():
        assert await BeanieDatabaseRepository().ping() is True

    async def it_returns_false_when_mongo_is_unreachable(monkeypatch: pytest.MonkeyPatch):
        class _UnreachableDatabase:
            async def command(self, *_args, **_kwargs):
                raise PyMongoError("no route to host")

        class _UnreachableCollection:
            database = _UnreachableDatabase()

        monkeypatch.setattr(UserModel, "get_pymongo_collection", classmethod(lambda _cls: _UnreachableCollection()))

        assert await BeanieDatabaseRepository().ping() is False
