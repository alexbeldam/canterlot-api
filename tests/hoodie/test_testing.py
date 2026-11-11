from typing import Any

import pytest
from beanie import PydanticObjectId
from pymongo import AsyncMongoClient

from canterlot.hoodie import Entity, HoodiePollingConfig, PollingPolicy, SyncKind, init_hoodie, sync_search
from canterlot.hoodie.exceptions import (
    DocumentNeverSearchableError,
    UnresolvedEntityReferenceError,
    UnsupportedSearchableFieldError,
)
from canterlot.hoodie.fields import SearchableType, TypeResolver, register_type_resolver, searchable
from canterlot.hoodie.testing import (
    delete_all_entities,
    disable_search,
    override_polling_config,
    override_registry,
    registered_entities,
    temporary_type_resolvers,
)
from tests.hoodie.entities import (
    UNREGISTERED_ENTITY_NAME,
    PlainTestEntity,
    SearchableTestEntity,
    abstract_root_entity,
    is_searchable,
    unresolvable_entity,
)
from tests.mongo_integration import DB_NAME

pytestmark = pytest.mark.asyncio(loop_scope="session")

_SEARCH_INDEX = "hoodie_test_searchable_entities_search"
_NEVER_SETTLES = HoodiePollingConfig(search_sync=PollingPolicy(max_attempts=2, initial_interval=0.01))


def describe_disable_search() -> None:
    async def it_skips_write_through_search_verification_inside_the_block(hoodie_client: AsyncMongoClient) -> None:
        with disable_search():
            await init_hoodie(hoodie_client[DB_NAME])

            # Without this skip, it would poll against a never-built index and eventually
            # raise DocumentNeverSearchableError instead of returning promptly.
            entity = await SearchableTestEntity(label="search-disabled").insert()

            assert entity.id is not None

    async def it_verifies_writes_against_the_search_index_again_after_the_block() -> None:
        with disable_search():
            pass

        entity = await SearchableTestEntity(label="search-reenabled").insert()

        assert await is_searchable(entity)

    async def it_reenables_search_when_the_block_raises() -> None:
        with pytest.raises(RuntimeError), disable_search():
            raise RuntimeError

        entity = await SearchableTestEntity(label="search-reenabled-after-error").insert()

        assert await is_searchable(entity)


def describe_override_registry() -> None:
    async def it_lets_init_hoodie_see_an_entity_defined_inside_the_block(hoodie_client: AsyncMongoClient) -> None:
        with override_registry():
            broken = unresolvable_entity()

            with pytest.raises(UnresolvedEntityReferenceError) as raised:
                await init_hoodie(hoodie_client[DB_NAME])

        assert raised.value.entity is broken
        assert raised.value.name == UNREGISTERED_ENTITY_NAME

    async def it_forgets_an_entity_defined_inside_the_block_once_it_exits(hoodie_client: AsyncMongoClient) -> None:
        with override_registry():
            unresolvable_entity()

        await init_hoodie(hoodie_client[DB_NAME])

        assert await PlainTestEntity(label="after-isolation").insert() is not None

    async def it_forgets_the_entity_even_when_the_block_raises(hoodie_client: AsyncMongoClient) -> None:
        with pytest.raises(RuntimeError), override_registry():
            unresolvable_entity()
            raise RuntimeError

        await init_hoodie(hoodie_client[DB_NAME])

    async def it_starts_with_no_registered_entities() -> None:
        with override_registry():
            assert registered_entities() == frozenset()

    async def it_restores_the_real_entities_once_the_block_exits() -> None:
        before = registered_entities()

        with override_registry():
            unresolvable_entity()

        assert registered_entities() == before

    async def it_lets_a_search_index_name_already_owned_by_a_real_entity_be_defined() -> None:
        with override_registry():

            class ShadowingIndexOwner(Entity):
                label: str = searchable(default="")

                class Settings:
                    name = "hoodie_test_shadowing_index_entities"
                    search_index = _SEARCH_INDEX

            assert ShadowingIndexOwner in registered_entities()

    async def it_frees_a_search_index_name_claimed_inside_the_block() -> None:
        with override_registry():

            class FirstIsolatedIndexOwner(Entity):
                label: str = searchable(default="")

                class Settings:
                    name = "hoodie_test_overridden_index_first"
                    search_index = "hoodie_test_overridden_index"

        with override_registry():

            class SecondIsolatedIndexOwner(Entity):
                label: str = searchable(default="")

                class Settings:
                    name = "hoodie_test_overridden_index_second"
                    search_index = "hoodie_test_overridden_index"

        assert issubclass(SecondIsolatedIndexOwner, Entity)


class _BoolResolver(TypeResolver):
    def resolve(self, annotation: Any) -> SearchableType | None:
        return SearchableType.STRING if annotation is bool else None


def _define_bool_searchable_entity() -> type[Entity]:
    class BoolSearchableTestEntity(Entity):
        flag: bool = searchable(default=False)

        class Settings:
            name = "hoodie_test_bool_searchable_entities"
            search_index = "hoodie_test_bool_searchable_index"

    return BoolSearchableTestEntity


def describe_temporary_type_resolvers() -> None:
    async def it_applies_a_resolver_registered_inside_the_block() -> None:
        with override_registry(), temporary_type_resolvers():
            register_type_resolver(_BoolResolver())

            assert _define_bool_searchable_entity() in registered_entities()

    async def it_forgets_that_resolver_once_the_block_exits() -> None:
        with override_registry():
            with temporary_type_resolvers():
                register_type_resolver(_BoolResolver())

            with pytest.raises(UnsupportedSearchableFieldError):
                _define_bool_searchable_entity()

    async def it_forgets_that_resolver_even_when_the_block_raises() -> None:
        with override_registry():
            with pytest.raises(RuntimeError), temporary_type_resolvers():
                register_type_resolver(_BoolResolver())
                raise RuntimeError

            with pytest.raises(UnsupportedSearchableFieldError):
                _define_bool_searchable_entity()

    async def it_keeps_resolvers_registered_before_the_block_in_effect_inside_it() -> None:
        with override_registry(), temporary_type_resolvers():

            class StringSearchableTestEntity(Entity):
                label: str = searchable(default="")

                class Settings:
                    name = "hoodie_test_string_searchable_entities"
                    search_index = "hoodie_test_string_searchable_index"

            assert StringSearchableTestEntity in registered_entities()


def describe_registered_entities() -> None:
    async def it_lists_an_entity_defined_inside_an_override_block() -> None:
        with override_registry():
            defined = unresolvable_entity()

            assert defined in registered_entities()

    async def it_no_longer_lists_that_entity_once_the_block_exits() -> None:
        with override_registry():
            defined = unresolvable_entity()

        assert defined not in registered_entities()

    async def it_does_not_list_an_abstract_root_entity() -> None:
        with override_registry():
            abstract_root = abstract_root_entity()

            assert abstract_root not in registered_entities()

    async def it_is_a_snapshot_unaffected_by_later_registrations() -> None:
        with override_registry():
            snapshot = registered_entities()
            defined = unresolvable_entity()

            assert defined not in snapshot


def describe_override_polling_config() -> None:
    async def it_applies_the_config_inside_the_block() -> None:
        with override_polling_config(_NEVER_SETTLES), pytest.raises(ExceptionGroup) as raised:
            await sync_search(_SEARCH_INDEX, [PydanticObjectId()], SyncKind.WRITE, session=None)

        assert isinstance(raised.value.exceptions[0], DocumentNeverSearchableError)

    async def it_restores_the_previous_config_after_the_block() -> None:
        with override_polling_config(_NEVER_SETTLES):
            pass

        entity = await SearchableTestEntity(label="polling-restored").insert()

        assert await is_searchable(entity)

    async def it_restores_the_previous_config_when_the_block_raises() -> None:
        with pytest.raises(RuntimeError), override_polling_config(_NEVER_SETTLES):
            raise RuntimeError

        entity = await SearchableTestEntity(label="polling-restored-after-error").insert()

        assert await is_searchable(entity)


def describe_delete_all_entities() -> None:
    async def it_deletes_documents_across_every_registered_entity() -> None:
        await PlainTestEntity(label="a").insert()
        await SearchableTestEntity(label="b").insert()

        await delete_all_entities()

        assert await PlainTestEntity.find_all().count() == 0
        assert await SearchableTestEntity.find_all().count() == 0
