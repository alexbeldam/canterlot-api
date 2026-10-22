from typing import TYPE_CHECKING, Any

from beanie import PydanticObjectId

if TYPE_CHECKING:
    from .entity import Entity
    from .fields import SearchableField
    from .sync import SyncKind


class HoodieError(Exception):
    """Base exception for all errors in the `canterlot.hoodie` framework integration.

    Distinct from `canterlot.exception.BusinessError`, which handles domain and
    business-logic rule conflicts.
    """


class DatabaseManagerNotOpenError(HoodieError, RuntimeError):
    """Raised when a `DatabaseManager` operation that needs a live connection is used before
    `open()` (or after `close()`)."""

    def __init__(self) -> None:
        super().__init__("DatabaseManager is not open.")


class TransactionError(HoodieError):
    """Base for business-rule conflicts raised specifically inside a transactional method body."""


class SessionError(HoodieError):
    """Base exception for session-related runtime or type errors."""


class UnmanagedSessionError(SessionError, RuntimeError):
    """Raised when a write/delete carries an explicit session but there's no active
    `deferred_search_sync`/`@transactional` batch to enqueue its search-sync verification
    into.

    :param kind: whether the write/delete that triggered this was a WRITE or a DELETE.
    :type kind: SyncKind
    """

    def __init__(self, kind: "SyncKind") -> None:
        super().__init__(f"{kind.title()} with session must be within a transactional context.")
        self.kind = kind


class InvalidSessionTypeError(SessionError, TypeError):
    """Raised when a write/delete's `session` argument is neither an `AsyncClientSession`
    instance nor `None`.

    :param session: the invalid value passed as the `session` argument.
    :type session: object
    """

    def __init__(self, session: object) -> None:
        actual_type = type(session).__qualname__
        super().__init__(
            f"Expected 'session' argument to be an AsyncClientSession instance or None, got {actual_type!r}"
        )
        self.session = session
        self.actual_type = actual_type


class SearchWithinTransactionError(SessionError, RuntimeError):
    """Raised when a search query is executed from within an active `@transactional` body.

    Atlas Search (`$search`/`$searchMeta`) aggregation stages cannot run inside a MongoDB
    multi-document transaction.

    :param index_name: the Atlas Search index the search was attempted against.
    :type index_name: str
    """

    def __init__(self, index_name: str) -> None:
        super().__init__(
            f"Cannot search index {index_name!r} from within an active transaction - Atlas "
            "Search cannot run inside a multi-document transaction. Call this search outside "
            "the @transactional body."
        )
        self.index_name = index_name


class EntityConfigurationError(HoodieError):
    """Base exception for errors during entity metadata and field definition."""


class SearchIndexConfigurationError(EntityConfigurationError):
    """Base exception for configuration errors related to search index setup."""


class HoodieNotInitializedError(EntityConfigurationError, RuntimeError):
    def __init__(self) -> None:
        super().__init__("No entities are registered; Hoodie has not been initialized.")


class UnknownSearchIndexError(SearchIndexConfigurationError, ValueError):
    def __init__(self, index_name: str) -> None:
        super().__init__(f"No entity class is registered for search index {index_name!r}.")
        self.index_name = index_name


class EmptySearchIndexNameError(SearchIndexConfigurationError, ValueError):
    """Raised at Entity subclass definition time when `Settings.search_index` is set to a
    blank string.
    """

    def __init__(self) -> None:
        super().__init__("Search index name cannot be empty.")


class UnsupportedSearchableFieldError(EntityConfigurationError, TypeError):
    """Raised at Entity subclass definition time when a searchable() field's type has no
    supported Atlas Search mapping.

    :param entity: the Entity subclass being defined.
    :type entity: type[Entity]
    :param field_name: the offending field's name (or dot-path, for a nested field).
    :type field_name: str
    :param annotation: the field's unsupported type annotation.
    :type annotation: Any
    :param reason: additional detail on why the type is unsupported, if any.
    :type reason: str | None
    """

    def __init__(
        self,
        entity: "type[Entity]",
        field_name: str,
        annotation: Any,
        *,
        reason: str | None = None,
    ) -> None:
        message = (
            f"Searchable field {field_name!r} on entity {entity.__name__!r} has an unsupported type {annotation!r}."
        )
        if reason:
            message += f" {reason}"

        super().__init__(message)
        self.entity = entity
        self.field_name = field_name
        self.annotation = annotation
        self.reason = reason


class UnexpectedSearchableFieldError(EntityConfigurationError, ValueError):
    """Raised at Entity subclass definition time when the class has searchable() fields but
    no Settings.search_index configured to index them into.

    :param entity: the Entity subclass being defined.
    :type entity: type[Entity]
    :param fields: the searchable() fields found with no search index to belong to.
    :type fields: set[SearchableField]
    """

    def __init__(
        self,
        entity: "type[Entity]",
        fields: "set[SearchableField]",
    ) -> None:
        sorted_fields = sorted(fields, key=lambda f: f.name)
        field_names = ", ".join(repr(field.name) for field in sorted_fields)
        super().__init__(
            f"Entity {entity.__name__!r} has searchable fields but no search index is configured: {field_names}."
        )
        self.entity = entity
        self.fields = fields


class DuplicateSearchIndexError(EntityConfigurationError, ValueError):
    """Raised at Entity subclass definition time when `Settings.search_index` reuses a name
    another Entity subclass already registered.

    :param index_name: the search index name being reused.
    :type index_name: str
    :param new_entity: the Entity subclass being defined, whose `search_index` collides.
    :type new_entity: type[Entity]
    :param existing_entity: the Entity subclass that already registered `index_name`.
    :type existing_entity: type[Entity]
    """

    def __init__(
        self,
        index_name: str,
        new_entity: "type[Entity]",
        existing_entity: "type[Entity]",
    ) -> None:
        super().__init__(
            f"Search index {index_name!r} is already registered by entity "
            f"{existing_entity.__name__!r}. Entity {new_entity.__name__!r} "
            f"cannot re-use the same index name."
        )
        self.index_name = index_name
        self.new_entity = new_entity
        self.existing_entity = existing_entity


class EntityNotSearchableError(EntityConfigurationError, ValueError):
    """Raised when `Entity.search()` is called on an Entity subclass with no
    `Settings.search_index` configured (or no `searchable()` domain fields), so there is no
    Atlas Search index to build a query against.

    :param entity: the Entity subclass with no search index.
    :type entity: type[Entity]
    """

    def __init__(self, entity: "type[Entity]") -> None:
        super().__init__(f"Entity {entity.__name__!r} has no search index configured; cannot build a search query.")
        self.entity = entity


class NotALinkFieldError(EntityConfigurationError, ValueError):
    """Raised when `ForeignSearchQuery` is asked to search through a field that isn't a
    Link/BackLink field on the given referencing entity.

    :param entity: the referencing Entity subclass.
    :type entity: type[Entity]
    :param field_name: the field name that isn't a Link/BackLink field on `entity`.
    :type field_name: str
    """

    def __init__(self, entity: "type[Entity]", field_name: str) -> None:
        super().__init__(f"{field_name!r} is not a Link/BackLink field on entity {entity.__name__!r}.")
        self.entity = entity
        self.field_name = field_name


class SyncError(HoodieError):
    """Base exception for errors related to @synced decorator operations."""


class SyncedOwnerTypeError(SyncError, TypeError):
    """Raised when bare `@synced`'s call carries a first positional argument that isn't an
    Entity instance or Entity subclass.

    :param owner: the invalid value passed as the call's first positional argument.
    :type owner: object
    """

    def __init__(self, owner: object) -> None:
        actual_type = type(owner).__qualname__
        super().__init__(f"Expected first argument to be an Entity instance or Entity subclass, got {actual_type!r}")
        self.owner = owner
        self.actual_type = actual_type


class SearchIndexError(HoodieError):
    """Base exception for runtime search index failures."""


class SearchIndexNeverDroppedError(SearchIndexError, RuntimeError):
    """Raised when a search index is still listed after being dropped, within the polling
    window (see `reset_hoodie`).

    :param index_name: the Atlas Search index that was never removed.
    :type index_name: str
    """

    def __init__(self, index_name: str) -> None:
        super().__init__(f"Search index {index_name!r} was never dropped.")
        self.index_name = index_name


class SearchIndexNeverQueryableError(SearchIndexError, RuntimeError):
    """Raised when a search index never becomes queryable within the polling window (see
    `init_hoodie`).

    :param index_name: the Atlas Search index that never became queryable.
    :type index_name: str
    """

    def __init__(self, index_name: str) -> None:
        super().__init__(f"Search index {index_name!r} never became queryable.")
        self.index_name = index_name


class DocumentNeverSearchableError(SearchIndexError, RuntimeError):
    """Raised when a document never became searchable within the polling window (see
    `sync_search`/`@synced`, which wrap this in an ExceptionGroup).

    :param index_name: the Atlas Search index the document never appeared in.
    :type index_name: str
    :param doc_id: the document's id.
    :type doc_id: PydanticObjectId
    """

    def __init__(self, index_name: str, doc_id: PydanticObjectId) -> None:
        super().__init__(f"Document {doc_id!r} never became searchable in index {index_name!r}.")
        self.index_name = index_name
        self.doc_id = doc_id


class DocumentNeverUnsearchableError(SearchIndexError, RuntimeError):
    """Raised when a document never became unsearchable within the polling window (see
    `sync_search`/`@synced`, which wrap this in an ExceptionGroup).

    :param index_name: the Atlas Search index the document never disappeared from.
    :type index_name: str
    :param doc_id: the document's id.
    :type doc_id: PydanticObjectId
    """

    def __init__(self, index_name: str, doc_id: PydanticObjectId) -> None:
        super().__init__(f"Document {doc_id!r} never became unsearchable in index {index_name!r}.")
        self.index_name = index_name
        self.doc_id = doc_id


class ProxyError(HoodieError):
    """Base exception for errors related to @_proxied decorator operations."""


class ProxiedMethodNotImplementedError(ProxyError, NotImplementedError):
    def __init__(self, target_cls: type, name: str) -> None:
        super().__init__(f"No superclass of {target_cls.__name__!r} implements {name!r}.")
        self.target_cls = target_cls
        self.name = name
