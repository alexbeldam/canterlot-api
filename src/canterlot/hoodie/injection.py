import functools
import inspect
from collections.abc import Callable, Iterable
from types import UnionType
from typing import TYPE_CHECKING, Any, Protocol, Self, Union, get_args, get_origin, overload

from beanie import BulkWriter, Document
from beanie.odm.queries.aggregation import AggregationQuery
from beanie.odm.queries.delete import DeleteMany, DeleteOne
from beanie.odm.queries.update import UpdateMany, UpdateOne
from pymongo.asynchronous.client_session import AsyncClientSession

from .registry import _CURRENT_SESSION

if TYPE_CHECKING:
    from .entity import Entity


# These call pymongo directly instead of through a query builder, so the builders' ambient
# session never reaches them.
_DIRECT_SESSION_METHOD_NAMES = ("insert", "insert_many", "replace_many", "distinct", "inspect_collection")


def _candidate_attrs(base: type[Document], *, is_app_defined_entity_subclass: bool) -> "Iterable[tuple[str, Any]]":
    if is_app_defined_entity_subclass:
        return base.__dict__.items()

    return ((name, base.__dict__[name]) for name in _DIRECT_SESSION_METHOD_NAMES if name in base.__dict__)


def _wrap_if_session_injectable(cls: "type[Entity]", attr_name: str, attr_value: Any) -> None:
    is_cls_method = isinstance(attr_value, classmethod)
    target_fn = attr_value.__func__ if is_cls_method else attr_value

    if not inspect.iscoroutinefunction(target_fn):
        return
    if getattr(target_fn, "__session_injected__", False):
        return

    wrapped = _inject_session_wrapper(target_fn)
    setattr(cls, attr_name, classmethod(wrapped) if is_cls_method else wrapped)


def _enable_session_injection(cls: "type[Entity]") -> None:
    from .entity import Entity

    seen_attrs: set[str] = set()

    for base in cls.__mro__:
        if not issubclass(base, Document):
            continue

        is_app_defined_entity_subclass = issubclass(base, Entity) and base is not Entity
        candidates = _candidate_attrs(base, is_app_defined_entity_subclass=is_app_defined_entity_subclass)

        for attr_name, attr_value in candidates:
            if attr_name.startswith("__") or attr_name in seen_attrs:
                continue

            seen_attrs.add(attr_name)
            _wrap_if_session_injectable(cls, attr_name, attr_value)


class _SessionInjectedCallable(Protocol):
    __session_injected__: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class _SessionInjectingWrapper:
    __session_injected__: bool = True

    def __init__(self, fn: Callable[..., Any], session_param: str, sig: inspect.Signature) -> None:
        functools.update_wrapper(self, fn)
        self._fn = fn
        self._session_param = session_param
        self._sig = sig

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        bound_args = self._sig.bind_partial(*args, **kwargs)

        if self._session_param not in bound_args.arguments or bound_args.arguments[self._session_param] is None:
            session = _CURRENT_SESSION.get()
            if session is not None:
                kwargs[self._session_param] = session

        return await self._fn(*args, **kwargs)

    def __get__(self, obj: Any, objtype: type | None = None) -> Callable[..., Any]:
        # A plain function set directly as a class attribute auto-binds `self`; a class instance
        # doesn't, so insert()/insert_many() would otherwise be called with `self` missing.
        if obj is None:
            return self
        return functools.partial(self, obj)


def _inject_session_wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
    unwrapped_target = inspect.unwrap(fn)
    try:
        sig = inspect.signature(unwrapped_target)
    except (ValueError, TypeError):  # pragma: no cover (only signature-less builtins/C callables raise this)
        return fn

    session_param: str | None = next(
        (param.name for param in sig.parameters.values() if _should_inject_session(param)),
        None,
    )

    if session_param is None:
        return fn

    wrapper: _SessionInjectedCallable = _SessionInjectingWrapper(fn, session_param, sig)
    # A callable class instance, not a plain function, so inspect.iscoroutinefunction() needs
    # this explicit mark to still recognize it as one, the same way a bare "async def" would be.
    inspect.markcoroutinefunction(wrapper)
    return wrapper


def _should_inject_session(param: inspect.Parameter) -> bool:
    ann = param.annotation

    if _is_async_client_session_type(ann):
        return True

    return param.name == "session" and ann in (inspect.Parameter.empty, Any)


def _is_async_client_session_type(annotation: Any) -> bool:
    if annotation is AsyncClientSession:
        return True
    if annotation in (inspect.Parameter.empty, Any):
        return False

    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(arg is AsyncClientSession for arg in get_args(annotation))

    return False


class _AmbientSession:
    def __set_name__(self, owner: type, name: str) -> None:
        self._slot = f"_explicit_{name}"

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> Self: ...
    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> AsyncClientSession | None: ...

    def __get__(self, obj: object | None, objtype: type | None = None) -> "Self | AsyncClientSession | None":
        if obj is None:
            return self

        explicit: AsyncClientSession | None = obj.__dict__.get(self._slot)
        return explicit if explicit is not None else _CURRENT_SESSION.get()

    def __set__(self, obj: object, value: AsyncClientSession | None) -> None:
        # Beanie passes a builder's session on to the next builder; storing the ambient one would pin
        # the transaction session on a builder that may be awaited after commit.
        obj.__dict__[self._slot] = None if value is _CURRENT_SESSION.get() else value


class _AmbientSessionMixin:
    session = _AmbientSession()


class _AmbientUpdateMany(_AmbientSessionMixin, UpdateMany):  # type: ignore[misc]
    pass


class _AmbientUpdateOne(_AmbientSessionMixin, UpdateOne):  # type: ignore[misc]
    pass


class _AmbientDeleteMany(_AmbientSessionMixin, DeleteMany):  # type: ignore[misc]
    pass


class _AmbientDeleteOne(_AmbientSessionMixin, DeleteOne):  # type: ignore[misc]
    pass


class _AmbientAggregationQuery(_AmbientSessionMixin, AggregationQuery):  # type: ignore[misc, type-arg]
    pass


class _AmbientBulkWriter(_AmbientSessionMixin, BulkWriter):  # type: ignore[misc]
    pass
