from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, overload

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from .exceptions import HoodieNotInitializedError, TransactionError
from .registry import _ALL_ENTITIES, _CURRENT_SESSION
from .sync import deferred_search_sync


class _Unset:
    __slots__ = ()


_UNSET = _Unset()

type _TransactionalBody[T, **P] = Callable[P, Awaitable[T]]
type _TransactionalMethod[R, **P] = Callable[P, Coroutine[Any, Any, R]]
type _Decorator[T, F, **P] = Callable[[_TransactionalBody[T, P]], _TransactionalMethod[T | F, P]]


@overload
def transactional[T, **P](
    func: _TransactionalBody[T, P],
    /,
) -> _TransactionalMethod[T, P]: ...


@overload
def transactional[T, F, **P](
    *,
    on_conflict: F,
) -> _Decorator[T, F, P]: ...


def transactional[T, F, **P](
    func: _TransactionalBody[T, P] | None = None,
    /,
    *,
    on_conflict: F | _Unset = _UNSET,
) -> _TransactionalMethod[T | F, P] | _Decorator[T, F, P]:
    """Runs the decorated method/function body inside a single real Mongo multi-document
    transaction, with every write's search-sync verification deferred and batched into one
    wait at commit time (see `deferred_search_sync`) instead of one wait per write.

    Every write made inside the body (through Entity's own methods, or through a query
    builder like `SomeEntity.find_one(...).update_one(...)`) automatically picks up the
    transaction's session with no need to pass `session=` explicitly.

    Nested @transactional calls share the same transaction: only the outermost call opens
    a real Mongo session/transaction; an inner call just runs its body inside the one
    already active. A nested call never absorbs a TransactionError: its own `on_conflict` is
    ignored and the exception propagates, so the whole shared transaction rolls back and only
    the outermost call's `on_conflict` (if any) applies.

    :param func: the method/function to wrap, used only when applying the decorator bare
        (`@transactional`, no parentheses).
    :type func: _TransactionalBody[T, P] | None
    :param on_conflict: fallback value returned when the body raises a `TransactionError`
        (or subclass) and this is the outermost call. Omit it (bare
        `@transactional`) to let every exception propagate instead. Raise a TransactionError
        subclass from the body to signal "this specific, anticipated conflict happened"
        rather than an unexpected failure.
    :type on_conflict: F | _Unset
    :returns: the decorated method/function. Its own return value is the body's return value
        on success, or `on_conflict` if it was declared, this is the outermost call, and
        the body raised a `TransactionError`.
    :rtype: _TransactionalMethod[T | F, P] | _Decorator[T, F, P]
    :raises TransactionError: propagates from the body when no `on_conflict` was declared
        for this call, or when this call is nested inside another.
    :raises Exception: any exception other than `TransactionError` always propagates,
        regardless of `on_conflict`.
    :raises HoodieNotInitializedError: if no Entity subclass has ever been imported/registered,
        so there is no Mongo client to open a session against.
    """

    def decorator(fn: _TransactionalBody[T, P]) -> _TransactionalMethod[T | F, P]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | F:
            is_nested = _CURRENT_SESSION.get() is not None
            try:
                return await _run_in_transaction(lambda: fn(*args, **kwargs))
            except TransactionError:
                # Absorbing in a nested call would leave the shared transaction to commit the
                # nested call's earlier writes, so only the outermost call may absorb.
                if is_nested or isinstance(on_conflict, _Unset):
                    raise
                return on_conflict

        return wrapper

    if func is None:
        return decorator

    return decorator(func)


async def _run_in_transaction[T](body: Callable[[], Awaitable[T]]) -> T:
    # Nested @transactional calls share the outer call's session instead of opening their own.
    existing_session = _CURRENT_SESSION.get()
    if existing_session is not None:
        return await body()

    async with _shared_client().start_session() as session, deferred_search_sync() as pending:

        async def attempt(s: AsyncClientSession) -> T:
            pending.clear()

            token = _CURRENT_SESSION.set(s)
            try:
                return await body()
            finally:
                _CURRENT_SESSION.reset(token)

        return await session.with_transaction(attempt)


def _shared_client() -> AsyncMongoClient:
    first = next(iter(_ALL_ENTITIES), None)
    if first is None:  # pragma: no cover (no Entity subclass has ever been imported)
        raise HoodieNotInitializedError

    return first.get_pymongo_collection().database.client
