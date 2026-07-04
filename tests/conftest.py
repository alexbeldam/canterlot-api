from collections.abc import AsyncIterator

import bcrypt
import mongomock.database
import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from canterlot.models.book import BookModel
from canterlot.models.club import ClubModel
from canterlot.models.invite import InviteModel
from canterlot.models.user import UserModel

_original_list_collection_names = mongomock.database.Database.list_collection_names
_original_gensalt = bcrypt.gensalt

bcrypt.gensalt = lambda rounds=4, prefix=b"2b": _original_gensalt(rounds, prefix)


def _list_collection_names_ignoring_unsupported_kwargs(self, filter=None, session=None, **_kwargs):
    return _original_list_collection_names(self, filter=filter, session=session)


@pytest.fixture(autouse=True)
async def _initialized_beanie() -> AsyncIterator[None]:
    mongomock.database.Database.list_collection_names = (  # type: ignore[method-assign]
        _list_collection_names_ignoring_unsupported_kwargs
    )
    try:
        client: AsyncMongoMockClient = AsyncMongoMockClient()
        await init_beanie(
            database=client["test"],  # type: ignore[arg-type]
            document_models=[UserModel, ClubModel, BookModel, InviteModel],
        )
        yield
    finally:
        mongomock.database.Database.list_collection_names = _original_list_collection_names  # type: ignore[method-assign]
