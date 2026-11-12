from typing import overload

from beanie import Link, PydanticObjectId
from beanie.odm.documents import Document


@overload
def link_id[T: Document](value: Link[T] | T) -> PydanticObjectId: ...
@overload
def link_id[T: Document](value: Link[T] | T | None) -> PydanticObjectId | None: ...
def link_id[T: Document](value: Link[T] | T | None) -> PydanticObjectId | None:
    """Reads the referenced document's id from a Link field.

    Works the same whether the field is still an unfetched `Link` (the default) or was
    populated by a `fetch_links=True` query, where it holds the fetched document instead.
    Typed for ObjectId-keyed targets; the id is returned as stored, never coerced.

    :param value: the Link field's current value, or None for an unset optional Link.
    :type value: Link[T] | T | None
    :returns: the referenced document's id, or None when `value` is None.
    :rtype: PydanticObjectId | None
    """
    if value is None:
        return None
    if isinstance(value, Link):
        return PydanticObjectId(value.ref.id)
    return value.id
