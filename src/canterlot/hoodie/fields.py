from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Any, TypeAliasType, Union, get_args, get_origin
from uuid import UUID

from beanie import PydanticObjectId
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

from .exceptions import UnsupportedSearchableFieldError

if TYPE_CHECKING:
    from .entity import Entity

_ATLAS_MAPPING_STRATEGIES: "dict[SearchableType, AtlasMappingStrategy]" = {}
_TYPE_RESOLVERS: list["TypeResolver"] = []

# The primary key's Atlas type varies per Entity subclass, unlike every other
# SearchableType, so it's never registered with _TYPE_RESOLVERS.
_ID_ATLAS_TYPES: dict[type, str] = {
    PydanticObjectId: "objectId",
    UUID: "string",
    str: "string",
    int: "number",
}

DefaultFactory = Callable[[], Any] | Callable[[dict[str, Any]], Any]
AtlasMappingStrategy = Callable[["Searchable"], "dict[str, Any] | list[dict[str, Any]]"]


class SearchableType(StrEnum):
    STRING = "STR"
    STRING_LIST = "LIST"
    ID = "ID"


@dataclass(frozen=True, slots=True)
class Searchable:
    facetable: bool = False
    analyzer: str = "lucene.standard"
    path: str | None = None


@dataclass(frozen=True, slots=True)
class SearchableField:
    name: str
    type: SearchableType
    config: Searchable
    path: str = ""
    # Only set for the synthetic `_id` entry; SearchableType.ID has no fixed Atlas mapping.
    resolved_atlas_type: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            object.__setattr__(self, "path", self.name)

    def extract_value(self, instance: Any) -> Any:
        current = instance
        for part in self.path.split("."):
            if current is None:
                return None
            current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
        return current

    def to_atlas_mapping(self) -> dict[str, Any] | list[dict[str, Any]]:
        if self.type is SearchableType.ID:
            return {"type": self.resolved_atlas_type}

        strategy = _ATLAS_MAPPING_STRATEGIES.get(self.type)
        if strategy is None:  # pragma: no cover (every SearchableType has a registered strategy)
            raise KeyError(f"No Atlas mapping strategy registered for SearchableType {self.type!r}")
        return strategy(self.config)

    def fingerprint_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type.value,
            "facetable": self.config.facetable,
            "analyzer": self.config.analyzer,
        }


class TypeResolver(ABC):
    @abstractmethod
    def resolve(self, annotation: Any) -> SearchableType | None: ...


class StringResolver(TypeResolver):
    def resolve(self, annotation: Any) -> SearchableType | None:
        if annotation is str:
            return SearchableType.STRING
        return None


def _is_string_container_origin(origin: Any) -> bool:
    # Must be a sequence/set container, excluding str/bytes.
    return isinstance(origin, type) and issubclass(origin, (Sequence, Set)) and not issubclass(origin, (str, bytes))


def _resolve_tuple_args(args: tuple[Any, ...]) -> SearchableType | None:
    if Ellipsis not in args:
        # Fixed-size tuple: every positional element must be str, or return None so
        # custom tuple resolvers can try.
        if not all(_unwrap_optional(arg) is str for arg in args):
            return None
        return SearchableType.STRING_LIST

    return SearchableType.STRING_LIST if _unwrap_optional(args[0]) is str else None


class SequenceResolver(TypeResolver):
    def resolve(self, annotation: Any) -> SearchableType | None:
        origin = get_origin(annotation)
        if not _is_string_container_origin(origin):
            return None

        args = get_args(annotation)
        if not args:
            raise ValueError(f"Untyped containers (e.g., {origin.__name__}) are not supported.")

        if origin is tuple:
            return _resolve_tuple_args(args)

        # Not a string collection -> return None to let downstream resolvers handle it
        return SearchableType.STRING_LIST if _unwrap_optional(args[0]) is str else None


def searchable(
    default: Any = ...,
    *,
    default_factory: DefaultFactory | None = None,
    facetable: bool = False,
    analyzer: str = "lucene.standard",
    path: str | None = None,
    **kwargs: Any,
) -> Any:
    """Declares a Pydantic field as part of an Entity's Atlas Search index.

    Drop-in replacement for `pydantic.Field(...)`. Supported field types are `str` and
    string collections (`list[str]`, `tuple[str, ...]`, a fixed-size all-str tuple,
    `set[str]`). A searchable() field can live directly on the Entity or on any nested
    Pydantic model reachable from it.

    :param default: same as `pydantic.Field`'s own `default`.
    :type default: Any
    :param default_factory: same as `pydantic.Field`'s own `default_factory`.
    :type default_factory: DefaultFactory | None
    :param facetable: also emits a non-analyzed `.keyword` sub-mapping for exact-match
        filtering/sorting, and a `stringFacet` type mapping on the same path so the field
        can be targeted directly by `SearchQuery.facet(...)`'s Atlas Search facet collector,
        alongside the analyzed mapping used for full-text search.
    :type facetable: bool
    :param analyzer: the Atlas Search analyzer for the (non-keyword) mapping.
    :type analyzer: str
    :param path: overrides the field's Atlas Search dot-path, if it should differ from
        where the field actually lives in the document.
    :type path: str | None
    :param kwargs: forwarded to `pydantic.Field`.
    :type kwargs: Any
    :returns: a `pydantic.FieldInfo` carrying the Searchable config in its metadata, exactly
        like `pydantic.Field(...)`'s own return value.
    :rtype: Any
    :raises UnsupportedSearchableFieldError: at Entity subclass definition time, if the
        field's type has no supported Atlas Search mapping.
    :raises UnexpectedSearchableFieldError: at Entity subclass definition time, if the
        owning Entity's `Settings.search_index` isn't set.
    """
    if default_factory is not None:
        field = Field(default_factory=default_factory, **kwargs)
    else:
        field = Field(default=default, **kwargs)

    field.metadata.append(Searchable(facetable=facetable, analyzer=analyzer, path=path))
    return field


def _get_searchable_config(field_info: FieldInfo) -> Searchable | None:
    for item in field_info.metadata:
        if isinstance(item, Searchable):
            return item
    return None


type _ModelQueue = deque[tuple[type[BaseModel], str, tuple[type[BaseModel], ...]]]


def _build_id_field(cls: "type[Entity]") -> SearchableField:
    id_annotation = _unwrap_optional(cls.model_fields["id"].annotation)
    atlas_type = _ID_ATLAS_TYPES.get(id_annotation)
    if atlas_type is None:
        raise UnsupportedSearchableFieldError(
            entity=cls,
            field_name="id",
            annotation=id_annotation,
            reason="No Atlas Search type mapping is registered for this primary key type.",
        )

    return SearchableField(
        name="_id",
        type=SearchableType.ID,
        config=Searchable(),
        path="_id",
        resolved_atlas_type=atlas_type,
    )


def _build_searchable_field(
    cls: "type[Entity]",
    name: str,
    current_path: str,
    field_info: FieldInfo,
) -> SearchableField | None:
    config = _get_searchable_config(field_info)
    if config is None:
        return None

    try:
        resolved_type = _resolve_searchable_type(field_info)
    except ValueError as err:
        raise UnsupportedSearchableFieldError(
            entity=cls,
            field_name=current_path,
            annotation=field_info.annotation,
            reason=str(err),
        ) from err

    return SearchableField(name=name, type=resolved_type, config=config, path=config.path or current_path)


def _enqueue_nested_model(
    queue: _ModelQueue,
    field_info: FieldInfo,
    current_path: str,
    ancestors: tuple[type[BaseModel], ...],
) -> None:
    if not field_info.annotation:
        return

    nested_model = _unwrap_pydantic_model(_unwrap_optional(field_info.annotation))
    if nested_model is not None and nested_model not in ancestors:
        queue.append((nested_model, current_path, (*ancestors, nested_model)))


def get_searchable_fields(cls: "type[Entity]") -> set[SearchableField]:
    searchable_fields: set[SearchableField] = {_build_id_field(cls)}

    # BFS queue: (model, path_prefix, ancestor_chain). ancestor_chain guards against cycles
    # per branch, so a model reused at two sibling fields is still visited both times.
    queue: _ModelQueue = deque([(cls, "", (cls,))])

    while queue:
        current_model, prefix, ancestors = queue.popleft()

        for name, field_info in current_model.model_fields.items():
            current_path = f"{prefix}.{name}" if prefix else name

            field = _build_searchable_field(cls, name, current_path, field_info)
            if field is not None:
                searchable_fields.add(field)

            _enqueue_nested_model(queue, field_info, current_path, ancestors)

    return searchable_fields


def _resolve_searchable_type(field_info: FieldInfo) -> SearchableType:
    annotation = field_info.annotation
    if annotation is None:  # pragma: no cover (a FieldInfo already attached to cls.model_fields always has one)
        raise ValueError("Field is missing a type annotation.")

    resolved = _unwrap_optional(annotation)

    for resolver in _TYPE_RESOLVERS:
        matched = resolver.resolve(resolved)
        if matched is not None:
            return matched

    raise ValueError(f"Annotation {annotation!r} is not supported for search indexing.")


def register_type_resolver(resolver: TypeResolver, *, prepend: bool = True) -> None:
    if prepend:
        _TYPE_RESOLVERS.insert(0, resolver)
    else:
        _TYPE_RESOLVERS.append(resolver)


def register_atlas_mapping_strategy(
    searchable_type: SearchableType,
    strategy: AtlasMappingStrategy,
) -> None:
    _ATLAS_MAPPING_STRATEGIES[searchable_type] = strategy


def _unwrap_pydantic_model(annotation: Any) -> type[BaseModel] | None:
    # Pydantic v2 eagerly concretizes a parametrized generic model (Wrapper[Profile]) into its
    # own real subclass, so the isinstance/issubclass check below already covers it.
    return annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None


def _unwrap_optional(annotation: Any) -> Any:
    """Peels PEP 695 type aliases, Annotated wrappers, and Optional down to the runtime type."""
    while True:
        if isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
            continue

        origin = get_origin(annotation)

        if origin is Annotated:
            annotation = get_args(annotation)[0]
            continue

        if origin is Union or origin is UnionType:
            args = [arg for arg in get_args(annotation) if arg is not type(None)]
            if len(args) != 1:
                raise ValueError(f"Complex unions like {annotation!r} are not supported for searchable fields.")
            annotation = args[0]
            continue

        return annotation


def _string_mapping_strategy(config: Searchable) -> dict[str, Any] | list[dict[str, Any]]:
    mapping: dict[str, Any] = {
        "type": "string",
        "analyzer": config.analyzer,
    }
    if not config.facetable:
        return mapping

    # multi only accepts other string analyzers; lucene.keyword doesn't tokenize, giving an
    # exact-match variant for filtering/sorting (sync.py verifies via `phrase`, not `equals`).
    mapping["multi"] = {
        "keyword": {
            "type": "string",
            "analyzer": "lucene.keyword",
        },
    }

    # stringFacet is Atlas's own mapping type for the facet collector and can't nest under
    # `multi`, so it needs its own top-level array entry alongside the analyzed mapping.
    return [mapping, {"type": "stringFacet"}]


# Default strategies for text/collections
register_atlas_mapping_strategy(SearchableType.STRING, _string_mapping_strategy)
register_atlas_mapping_strategy(SearchableType.STRING_LIST, _string_mapping_strategy)
register_type_resolver(StringResolver())
register_type_resolver(SequenceResolver())
