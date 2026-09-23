from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from canterlot.config import search_index
from canterlot.models import BookModel, ClubModel, SearchIndexSpec


class _FakeCursor:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self._docs = docs

    async def to_list(self) -> list[dict[str, object]]:
        return self._docs


def _make_collection(
    name: str,
    list_results: list[list[dict[str, object]]] | Callable[[], list[dict[str, object]]],
) -> MagicMock:
    collection = MagicMock()
    collection.name = name
    if callable(list_results):
        collection.list_search_indexes = AsyncMock(side_effect=lambda *_a, **_kw: _FakeCursor(list_results()))
    else:
        collection.list_search_indexes = AsyncMock(side_effect=[_FakeCursor(docs) for docs in list_results])
    collection.create_search_index = AsyncMock()
    return collection


def _stub_collection(monkeypatch: pytest.MonkeyPatch, model: type, collection: MagicMock) -> None:
    monkeypatch.setattr(model, "get_pymongo_collection", classmethod(lambda _cls: collection))


def _register(monkeypatch: pytest.MonkeyPatch, **specs: SearchIndexSpec) -> None:
    monkeypatch.setattr(search_index, "SEARCH_INDEX_MAP", specs)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    sleep = AsyncMock()
    monkeypatch.setattr(search_index.asyncio, "sleep", sleep)
    return sleep


def describe_ensure_registered_search_indexes():
    async def it_skips_creation_when_the_index_already_exists(
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleeping: AsyncMock,
    ):
        collection = _make_collection("books", [[{"name": "books_search", "queryable": True}]])
        _stub_collection(monkeypatch, BookModel, collection)
        _register(
            monkeypatch,
            books_search=SearchIndexSpec(model=BookModel, definition={"mappings": {"dynamic": True}}),
        )

        await search_index.ensure_registered_search_indexes()

        collection.create_search_index.assert_not_awaited()
        assert collection.list_search_indexes.await_count == 1
        _no_real_sleeping.assert_not_awaited()

    async def it_creates_the_index_when_it_does_not_exist(
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleeping: AsyncMock,
    ):
        collection = _make_collection("books", [[], [{"name": "books_search", "queryable": True}]])
        _stub_collection(monkeypatch, BookModel, collection)
        definition = {"mappings": {"dynamic": True}}
        _register(monkeypatch, books_search=SearchIndexSpec(model=BookModel, definition=definition))

        await search_index.ensure_registered_search_indexes()

        collection.create_search_index.assert_awaited_once()
        search_index_model = collection.create_search_index.await_args.args[0]
        assert search_index_model.document["name"] == "books_search"
        assert search_index_model.document["definition"] == definition
        _no_real_sleeping.assert_not_awaited()

    async def it_polls_until_the_index_becomes_queryable(
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleeping: AsyncMock,
    ):
        collection = _make_collection(
            "books",
            [
                [{"name": "books_search", "queryable": False}],
                [{"name": "books_search", "queryable": False}],
                [{"name": "books_search", "queryable": False}],
                [{"name": "books_search", "queryable": True}],
            ],
        )
        _stub_collection(monkeypatch, BookModel, collection)
        _register(
            monkeypatch,
            books_search=SearchIndexSpec(model=BookModel, definition={"mappings": {"dynamic": True}}),
        )

        await search_index.ensure_registered_search_indexes()

        assert collection.list_search_indexes.await_count == 4
        assert _no_real_sleeping.await_count == 3

    async def it_raises_when_the_index_never_becomes_queryable_before_max_attempts(
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleeping: AsyncMock,
    ):
        collection = _make_collection("books", lambda: [{"name": "books_search", "queryable": False}])
        _stub_collection(monkeypatch, BookModel, collection)
        _register(
            monkeypatch,
            books_search=SearchIndexSpec(model=BookModel, definition={"mappings": {"dynamic": True}}),
        )

        with pytest.raises(RuntimeError, match="never became queryable"):
            await search_index.ensure_registered_search_indexes()

        assert _no_real_sleeping.await_count == 30

    async def it_provisions_every_entry_in_the_search_index_map(
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleeping: AsyncMock,
    ):
        first_collection = _make_collection("books", [[{"name": "books_search", "queryable": True}]])
        second_collection = _make_collection("clubs", [[{"name": "clubs_search", "queryable": True}]])
        _stub_collection(monkeypatch, BookModel, first_collection)
        _stub_collection(monkeypatch, ClubModel, second_collection)
        _register(
            monkeypatch,
            books_search=SearchIndexSpec(model=BookModel, definition={"mappings": {"a": 1}}),
            clubs_search=SearchIndexSpec(model=ClubModel, definition={"mappings": {"b": 2}}),
        )

        await search_index.ensure_registered_search_indexes()

        first_collection.list_search_indexes.assert_awaited_once()
        second_collection.list_search_indexes.assert_awaited_once()
