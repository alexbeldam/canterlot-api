import pytest
from beanie import Link, PydanticObjectId
from bson import DBRef

from canterlot.hoodie import complete_forward_references, link_id
from canterlot.hoodie.exceptions import EntityLinkWithoutIdError, UnresolvedEntityReferenceError
from canterlot.hoodie.testing import override_registry
from tests.hoodie.cyclic_child import CyclicChild
from tests.hoodie.cyclic_parent import CyclicParent
from tests.hoodie.entities import (
    UNREGISTERED_ENTITY_NAME,
    LinkedTestEntity,
    PlainTestEntity,
    SearchableTestEntity,
    unresolvable_entity,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _insert_linked_owner() -> tuple[LinkedTestEntity, PydanticObjectId]:
    target = await SearchableTestEntity(label="linked").insert()
    plain = await PlainTestEntity().insert()
    assert target.id is not None
    assert plain.id is not None

    owner = await LinkedTestEntity(
        target=SearchableTestEntity.link_from_id(target.id),
        unsearchable_target=PlainTestEntity.link_from_id(plain.id),
    ).insert()

    return owner, target.id


def describe_to_link():
    async def it_builds_an_unfetched_link_to_the_document():
        saved = await PlainTestEntity().insert()

        link = saved.to_link()

        assert isinstance(link, Link)
        assert link.ref == DBRef(PlainTestEntity.get_collection_name(), saved.id)
        assert link.document_class is PlainTestEntity

    async def it_rejects_a_document_that_has_no_id_yet():
        unsaved = PlainTestEntity()
        unsaved.id = None

        with pytest.raises(EntityLinkWithoutIdError) as raised:
            unsaved.to_link()

        assert raised.value.entity is PlainTestEntity

    async def it_round_trips_as_a_dbref_in_the_stored_document():
        owner, target_id = await _insert_linked_owner()

        raw = await LinkedTestEntity.get_pymongo_collection().find_one({"_id": owner.id})

        assert raw is not None
        assert raw["target"] == DBRef(SearchableTestEntity.get_collection_name(), target_id)


def describe_link_id():
    async def it_reads_the_id_from_an_unfetched_link():
        target_id = PydanticObjectId()

        assert link_id(PlainTestEntity.link_from_id(target_id)) == target_id

    async def it_reads_the_id_from_a_fetched_document():
        owner, target_id = await _insert_linked_owner()

        fetched = await LinkedTestEntity.find_one(LinkedTestEntity.id == owner.id, fetch_links=True)

        assert fetched is not None
        assert link_id(fetched.target) == target_id

    async def it_returns_none_for_a_missing_optional_link():
        assert link_id(None) is None


def describe_circular_back_links():
    async def it_completes_an_entity_whose_back_link_target_is_only_imported_for_type_checking():
        assert CyclicParent.__pydantic_complete__

    async def it_populates_the_back_link_when_links_are_fetched():
        parent = await CyclicParent().insert()
        await CyclicChild(parent=parent.to_link()).insert()

        fetched = await CyclicParent.get(parent.id, fetch_links=True)

        assert fetched is not None
        assert len(fetched.children) == 1

    async def it_is_safe_to_complete_forward_references_again():
        complete_forward_references()

        assert CyclicParent.__pydantic_complete__

    async def it_raises_a_hoodie_error_naming_a_reference_to_an_unregistered_entity():
        with override_registry():
            broken = unresolvable_entity()

            with pytest.raises(UnresolvedEntityReferenceError) as raised:
                complete_forward_references()

        assert raised.value.entity is broken
        assert raised.value.name == UNREGISTERED_ENTITY_NAME
