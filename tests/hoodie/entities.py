from datetime import datetime
from typing import Any

from beanie import BackLink, Link
from pydantic import BaseModel, Field, create_model
from pymongo.asynchronous.client_session import AsyncClientSession

from canterlot.hoodie import Entity
from canterlot.hoodie.fields import searchable


class PlainTestEntity(Entity):
    label: str = "default"

    class Settings:
        name = "hoodie_test_plain_entities"


class CustomMethodTestEntity(Entity):
    counter: int = 0

    class Settings:
        name = "hoodie_test_custom_method_entities"

    async def bump_directly(self, session: AsyncClientSession | None = None) -> None:
        # Bypasses beanie's query builders entirely, like insert()/insert_many(), exercising
        # _enable_session_injection's generic scan for app-defined methods.
        await self.get_pymongo_collection().update_one(
            {"_id": self.id},
            {"$inc": {"counter": 1}},
            session=session,
        )


class NoSessionMethodTestEntity(Entity):
    counter: int = 0

    class Settings:
        name = "hoodie_test_no_session_method_entities"

    async def double_counter(self) -> int:
        # No session-shaped parameter: exercises _enable_session_injection's fallback for a
        # custom coroutine method it deliberately leaves unwrapped.
        return self.counter * 2


class RequiredSessionMethodTestEntity(Entity):
    counter: int = 0

    class Settings:
        name = "hoodie_test_required_session_method_entities"

    async def bump_directly(self, session: AsyncClientSession) -> None:
        # session is annotated bare (not Optional), exercising _is_async_client_session_type's
        # direct-match branch rather than its Optional[...] union branch.
        await self.get_pymongo_collection().update_one(
            {"_id": self.id},
            {"$inc": {"counter": 1}},
            session=session,
        )


class SubCustomMethodTestEntity(CustomMethodTestEntity):
    # No methods of its own: exercises _enable_session_injection's "already wrapped" skip
    # for a method inherited already-wrapped from the parent's __dict__.
    class Settings:
        name = "hoodie_test_sub_custom_method_entities"


class SessionPathItem(Entity):
    name: str
    n: int = 0
    ts: datetime | None = None

    class Settings:
        name = "hoodie_test_session_path_items"
        use_state_management = True


class SessionPathParent(Entity):
    name: str
    child: Link[SessionPathItem] | None = None
    kids: list[Link[SessionPathItem]] = Field(default_factory=list)

    class Settings:
        name = "hoodie_test_session_path_parents"
        use_state_management = True


class Profile(BaseModel):
    bio: str = searchable(default="")


class SearchableTestEntity(Entity):
    # Single workhorse searchable entity for every hoodie integration test: one Atlas index
    # covers text, facet, nested, and plain-Mongo-only fields instead of one index each.
    label: str = searchable(default="default")
    genre: str = searchable(default="", facetable=True)
    category: str = "default"
    profile: Profile = Profile()

    class Settings:
        name = "hoodie_test_searchable_entities"
        search_index = "hoodie_test_searchable_entities_search"


class LabelProjection(BaseModel):
    label: str


class LinkedTestEntity(Entity):
    label: str = "default"
    target: Link[SearchableTestEntity]
    unsearchable_target: Link[PlainTestEntity]

    class Settings:
        name = "hoodie_test_linked_entities"


UNREGISTERED_ENTITY_NAME = "NotARegisteredEntity"


def unresolvable_entity() -> type[Entity]:
    # Built at runtime so the dangling forward reference never appears as an undefined name
    # in an annotation. Registers on definition: call it inside override_registry().
    back_link: Any = BackLink
    list_of: Any = list
    return create_model(
        "UnresolvableTestEntity",
        __base__=Entity,
        others=(
            list_of[back_link[UNREGISTERED_ENTITY_NAME]],
            Field(default_factory=list, json_schema_extra={"original_field": "owner"}),
        ),
    )


def abstract_root_entity() -> type[Entity]:
    class AbstractRootTestEntity(Entity):
        class Settings:
            is_root = True

    return AbstractRootTestEntity


async def is_searchable(entity: SearchableTestEntity) -> bool:
    results = await SearchableTestEntity.search().filter_equals("_id", entity.id).limit(1).to_list()
    return bool(results)
