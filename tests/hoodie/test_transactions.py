import pytest
from beanie import PydanticObjectId
from beanie.operators import Set

from canterlot.hoodie import TransactionError, transactional
from tests.hoodie.entities import PlainTestEntity, SearchableTestEntity, is_searchable

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _Unrelated(Exception):
    pass


class _Conflict(TransactionError):
    pass


class _SampleOperations:
    @transactional
    async def create_two_plain_entities(self, label_a: str, label_b: str) -> list[PlainTestEntity]:
        entity_a = PlainTestEntity(label=label_a)
        entity_b = PlainTestEntity(label=label_b)
        await entity_a.insert()
        await entity_b.insert()
        return [entity_a, entity_b]

    @transactional
    async def insert_searchable(self, label: str) -> SearchableTestEntity:
        return await SearchableTestEntity(label=label).insert()

    @transactional
    async def insert_then_raise(self, label: str) -> None:
        await PlainTestEntity(label=label).insert()
        raise _Unrelated("unhandled")

    @transactional(on_conflict=False)
    async def rename_or_conflict(self, entity_id: PydanticObjectId, new_label: str) -> bool:
        entity = await PlainTestEntity.get(entity_id)
        if entity is None:
            raise _Conflict
        entity.label = new_label
        await entity.save()
        return True

    @transactional(on_conflict=False)
    async def raise_unrelated_bool(self) -> bool:
        raise _Unrelated("unhandled")

    @transactional(on_conflict=None)
    async def rename_or_conflict_returning(self, entity_id: PydanticObjectId, new_label: str) -> PlainTestEntity:
        entity = await PlainTestEntity.get(entity_id)
        if entity is None:
            raise _Conflict
        entity.label = new_label
        await entity.save()
        return entity

    @transactional(on_conflict=None)
    async def raise_unrelated_optional(self) -> PlainTestEntity:
        raise _Unrelated("unhandled")

    @transactional
    async def call_inner_conflict_and_return(self, entity_id: PydanticObjectId, new_label: str) -> bool:
        return await self.rename_or_conflict(entity_id, new_label)

    @transactional(on_conflict=False)
    async def inner_insert_then_conflict(self, label: str) -> bool:
        await PlainTestEntity(label=label).insert()
        raise _Conflict

    @transactional
    async def outer_without_on_conflict(self, label: str) -> bool:
        return await self.inner_insert_then_conflict(label)

    @transactional(on_conflict="outer-fallback")
    async def outer_with_on_conflict(self, label: str) -> bool | str:
        return await self.inner_insert_then_conflict(label)

    @transactional
    async def insert_then_call_inner_unrelated_raise(self, label: str) -> None:
        await PlainTestEntity(label=label).insert()
        await self.raise_unrelated_bool()


def describe_transactional() -> None:
    async def it_commits_every_write_made_inside_the_body() -> None:
        ops = _SampleOperations()

        created = await ops.create_two_plain_entities("txn-label-a", "txn-label-b")

        assert len(created) == 2
        assert await PlainTestEntity.find(PlainTestEntity.label == "txn-label-a").count() == 1
        assert await PlainTestEntity.find(PlainTestEntity.label == "txn-label-b").count() == 1

    async def it_leaves_a_committed_insert_searchable() -> None:
        ops = _SampleOperations()

        entity = await ops.insert_searchable("txn-searchable-commit")

        assert await is_searchable(entity)

    async def it_rolls_back_and_propagates_on_an_unhandled_exception() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Unrelated):
            await ops.insert_then_raise("txn-label-rolled-back")

        assert await PlainTestEntity.find(PlainTestEntity.label == "txn-label-rolled-back").count() == 0


def describe_transactional_with_on_conflict_false() -> None:
    async def it_returns_true_and_persists_the_write_on_success() -> None:
        entity = await PlainTestEntity(label="rename-target").insert()
        ops = _SampleOperations()

        matched = await ops.rename_or_conflict(PydanticObjectId(entity.id), "renamed-via-decorator")

        assert matched is True
        found = await PlainTestEntity.get(entity.id)
        assert found is not None
        assert found.label == "renamed-via-decorator"

    async def it_returns_false_and_rolls_back_on_the_declared_conflict() -> None:
        ops = _SampleOperations()

        matched = await ops.rename_or_conflict(PydanticObjectId(), "does-not-matter")

        assert matched is False

    async def it_still_propagates_an_exception_that_is_not_the_declared_conflict() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Unrelated):
            await ops.raise_unrelated_bool()


def describe_transactional_with_on_conflict_none() -> None:
    async def it_returns_the_bodys_result_on_success() -> None:
        entity = await PlainTestEntity(label="rename-target-2").insert()
        ops = _SampleOperations()

        renamed = await ops.rename_or_conflict_returning(PydanticObjectId(entity.id), "renamed-again")

        assert renamed is not None
        assert renamed.label == "renamed-again"

    async def it_returns_none_on_the_declared_conflict() -> None:
        ops = _SampleOperations()

        result = await ops.rename_or_conflict_returning(PydanticObjectId(), "does-not-matter")

        assert result is None

    async def it_still_propagates_an_exception_that_is_not_the_declared_conflict() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Unrelated):
            await ops.raise_unrelated_optional()


def describe_transactional_nesting() -> None:
    async def it_propagates_a_nested_conflict_to_the_outermost_call_instead_of_absorbing_it() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Conflict):
            await ops.call_inner_conflict_and_return(PydanticObjectId(), "does-not-matter")

    async def it_rolls_back_a_nested_calls_writes_when_it_raises_a_conflict() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Conflict):
            await ops.outer_without_on_conflict("nested-conflict-rolled-back")

        assert await PlainTestEntity.find(PlainTestEntity.label == "nested-conflict-rolled-back").count() == 0

    async def it_applies_only_the_outermost_calls_on_conflict_to_a_nested_conflict() -> None:
        ops = _SampleOperations()

        result = await ops.outer_with_on_conflict("nested-conflict-outer-fallback")

        assert result == "outer-fallback"
        assert await PlainTestEntity.find(PlainTestEntity.label == "nested-conflict-outer-fallback").count() == 0

    async def it_shares_one_transaction_across_a_nested_call_so_an_inner_failure_rolls_back_the_outer_write() -> None:
        ops = _SampleOperations()

        with pytest.raises(_Unrelated):
            await ops.insert_then_call_inner_unrelated_raise("nested-rolled-back")

        assert await PlainTestEntity.find(PlainTestEntity.label == "nested-rolled-back").count() == 0


async def _found_by_label(label: str) -> bool:
    return bool(await SearchableTestEntity.search().phrase("label", label).to_list())


def describe_transactional_searchable_writes() -> None:
    async def it_leaves_a_saved_change_searchable_after_commit() -> None:
        entity = await SearchableTestEntity(label="save-before").insert()

        @transactional
        async def save_change() -> None:
            entity.label = "save-after"
            await entity.save()

        await save_change()

        assert await _found_by_label("save-after")

    async def it_leaves_a_replaced_change_searchable_after_commit() -> None:
        entity = await SearchableTestEntity(label="replace-before").insert()

        @transactional
        async def replace_change() -> None:
            entity.label = "replace-after"
            await entity.replace()

        await replace_change()

        assert await _found_by_label("replace-after")

    async def it_leaves_an_updated_change_searchable_after_commit() -> None:
        entity = await SearchableTestEntity(label="update-before").insert()

        @transactional
        async def update_change() -> None:
            await entity.update(Set({SearchableTestEntity.label: "update-after"}))

        await update_change()

        assert await _found_by_label("update-after")

    async def it_leaves_the_index_untouched_when_the_body_raises_after_a_save() -> None:
        entity = await SearchableTestEntity(label="rollback-before").insert()

        @transactional
        async def save_then_fail() -> None:
            entity.label = "rollback-after"
            await entity.save()
            raise _Unrelated("unhandled")

        with pytest.raises(_Unrelated):
            await save_then_fail()

        assert not await _found_by_label("rollback-after")
