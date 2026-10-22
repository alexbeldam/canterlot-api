import pytest
from beanie import Document
from pymongo import AsyncMongoClient

from canterlot.hoodie import ForeignSearchQuery, Scored, SearchQuery, transactional
from canterlot.hoodie.exceptions import (
    EntityNotSearchableError,
    NotALinkFieldError,
    SearchWithinTransactionError,
    UnmanagedSessionError,
)
from tests.hoodie.entities import (
    LabelProjection,
    LinkedTestEntity,
    PlainTestEntity,
    SearchableTestEntity,
    is_searchable,
)


class _PlainBeanieDocument(Document):
    label: str = "default"

    class Settings:
        name = "hoodie_test_plain_beanie_documents"


async def _insert_searchable(
    label: str,
    *,
    genre: str = "",
    category: str = "default",
) -> SearchableTestEntity:
    return await SearchableTestEntity(label=label, genre=genre, category=category).insert()


async def _insert_plain(label: str) -> PlainTestEntity:
    return await PlainTestEntity(label=label).insert()


async def _insert_linked(
    label: str,
    target: SearchableTestEntity,
    unsearchable_target: PlainTestEntity,
) -> LinkedTestEntity:
    # Beanie's Link fields accept a real Document instance directly at runtime (it's wrapped
    # into a Link on save), but pyright's synthesized field type stays Link[...] only.
    return await LinkedTestEntity(
        label=label,
        target=target,  # pyright: ignore[reportArgumentType]
        unsearchable_target=unsearchable_target,  # pyright: ignore[reportArgumentType]
    ).insert()


def describe_entity_search() -> None:
    def it_raises_when_the_entity_has_no_search_index_configured() -> None:
        with pytest.raises(EntityNotSearchableError):
            PlainTestEntity.search()

    @pytest.mark.asyncio(loop_scope="session")
    async def it_raises_only_when_executed_from_within_an_active_transaction() -> None:
        @transactional
        async def search_inside_transaction() -> list[SearchableTestEntity]:
            return await SearchableTestEntity.search().text("label", "hello").to_list()

        with pytest.raises(SearchWithinTransactionError) as exc_info:
            await search_inside_transaction()

        assert exc_info.value.index_name == "hoodie_test_searchable_entities_search"

    @pytest.mark.asyncio(loop_scope="session")
    async def it_allows_running_a_query_built_inside_a_transaction_once_it_has_returned() -> None:
        @transactional
        async def build_inside_transaction() -> SearchQuery[SearchableTestEntity]:
            return SearchableTestEntity.search().text("label", "hello")

        query = await build_inside_transaction()

        assert await query.to_list() == []

    def it_returns_a_search_query_bound_to_the_entitys_own_index() -> None:
        query = SearchableTestEntity.search()

        assert isinstance(query, SearchQuery)


def describe_to_compound() -> None:
    def it_puts_text_clauses_under_must() -> None:
        compound = SearchableTestEntity.search().text("label", "hello").to_compound()

        assert compound == {"must": [{"text": {"query": "hello", "path": "label"}}]}

    def it_adds_fuzzy_to_a_text_clause_when_requested() -> None:
        compound = SearchableTestEntity.search().text("label", "hello", fuzzy=True).to_compound()

        assert compound["must"][0]["text"]["fuzzy"] == {}

    def it_puts_phrase_clauses_under_must() -> None:
        compound = SearchableTestEntity.search().phrase("label", "hello world").to_compound()

        assert compound == {"must": [{"phrase": {"path": "label", "query": "hello world"}}]}

    def it_puts_filter_in_clauses_under_filter() -> None:
        compound = SearchableTestEntity.search().filter_in("_id", [1, 2]).to_compound()

        assert compound == {"filter": [{"in": {"path": "_id", "value": [1, 2]}}]}

    def it_puts_filter_equals_clauses_under_filter() -> None:
        compound = SearchableTestEntity.search().filter_equals("_id", 1).to_compound()

        assert compound == {"filter": [{"equals": {"path": "_id", "value": 1}}]}

    def it_puts_filter_not_equals_clauses_under_must_not() -> None:
        compound = SearchableTestEntity.search().filter_not_equals("_id", 1).to_compound()

        assert compound == {"mustNot": [{"equals": {"path": "_id", "value": 1}}]}

    def it_omits_should_and_minimum_should_match_when_no_should_clauses_were_added() -> None:
        compound = SearchableTestEntity.search().text("label", "hello").to_compound()

        assert "should" not in compound
        assert "minimumShouldMatch" not in compound

    def it_wraps_a_nested_search_query_as_a_compound_clause_under_should() -> None:
        sub_query = SearchableTestEntity.search().filter_equals("_id", 1)

        compound = SearchableTestEntity.search().should(sub_query).to_compound()

        assert compound["should"] == [{"compound": {"filter": [{"equals": {"path": "_id", "value": 1}}]}}]
        assert compound["minimumShouldMatch"] == 1

    def it_passes_through_a_raw_dict_clause_under_should() -> None:
        compound = SearchableTestEntity.search().should({"in": {"path": "_id", "value": [1]}}).to_compound()

        assert compound["should"] == [{"in": {"path": "_id", "value": [1]}}]

    def it_sets_minimum_should_match_from_the_should_call() -> None:
        compound = (
            SearchableTestEntity.search()
            .should({"in": {"path": "_id", "value": [1]}}, minimum_should_match=2)
            .to_compound()
        )

        assert compound["minimumShouldMatch"] == 2


def describe_to_pipeline() -> None:
    def it_builds_a_bare_search_stage_with_the_entitys_own_index() -> None:
        pipeline = SearchableTestEntity.search().filter_equals("_id", 1).to_pipeline()

        assert pipeline == [
            {
                "$search": {
                    "index": "hoodie_test_searchable_entities_search",
                    "compound": {"filter": [{"equals": {"path": "_id", "value": 1}}]},
                }
            }
        ]

    def it_appends_a_limit_stage_when_limit_is_given() -> None:
        pipeline = SearchableTestEntity.search().filter_equals("_id", 1).limit(5).to_pipeline()

        assert pipeline[-1] == {"$limit": 5}

    def it_nests_the_compound_under_facet_operator_when_facets_were_added() -> None:
        query = SearchableTestEntity.search().text("label", "hello")
        query.facet("genreFacet", "genre", "string")

        stage = query.to_pipeline()[0]["$search"]
        assert "compound" not in stage
        assert stage["facet"]["operator"] == {"compound": {"must": [{"text": {"query": "hello", "path": "label"}}]}}
        assert stage["facet"]["facets"] == {"genreFacet": {"type": "string", "path": "genre"}}


def describe_facet() -> None:
    def it_stores_the_facet_definition_with_any_extra_options() -> None:
        query = SearchableTestEntity.search().facet("yearFacet", "year", "number", boundaries=[2000, 2010])

        stage = query.to_pipeline()[0]["$search"]
        assert stage["facet"]["facets"]["yearFacet"] == {
            "type": "number",
            "path": "year",
            "boundaries": [2000, 2010],
        }


def describe_project() -> None:
    def it_adds_no_project_stage_when_not_called() -> None:
        pipeline = SearchableTestEntity.search().filter_equals("_id", 1).to_pipeline()

        assert not any("$project" in stage for stage in pipeline)

    def it_adds_a_project_stage_matching_the_projection_models_fields() -> None:
        pipeline = SearchableTestEntity.search().filter_equals("_id", 1).project(LabelProjection).to_pipeline()

        assert pipeline[-1] == {"$project": {"label": 1}}

    def it_is_a_noop_when_given_none() -> None:
        pipeline = SearchableTestEntity.search().filter_equals("_id", 1).project(None).to_pipeline()

        assert not any("$project" in stage for stage in pipeline)

    @pytest.mark.asyncio(loop_scope="session")
    async def it_returns_projected_results_instead_of_the_full_entity() -> None:
        await _insert_searchable("projected result")

        items = await SearchableTestEntity.search().text("label", "projected").project(LabelProjection).to_list()

        assert items == [LabelProjection(label="projected result")]

    @pytest.mark.asyncio(loop_scope="session")
    async def it_projects_a_paginated_page_of_results() -> None:
        await _insert_searchable("projected page result")

        query = SearchableTestEntity.search().text("label", "projected page").project(LabelProjection)
        page = await query.paginate(1, 10)

        assert page["items"] == [LabelProjection(label="projected page result")]


@pytest.mark.asyncio(loop_scope="session")
def describe_to_list() -> None:
    async def it_returns_matching_entities_for_a_text_query() -> None:
        await _insert_searchable("ponies of canterlot")
        await _insert_searchable("unrelated document")

        items = await SearchableTestEntity.search().text("label", "canterlot").to_list()

        assert [item.label for item in items] == ["ponies of canterlot"]

    async def it_returns_scored_results_when_scored_is_called() -> None:
        await _insert_searchable("scored result")

        items = await SearchableTestEntity.search().text("label", "scored").scored().to_list()

        assert len(items) == 1
        assert isinstance(items[0], Scored)
        assert items[0].item.label == "scored result"
        assert items[0].score > 0

    async def it_limits_results_when_limit_is_given() -> None:
        await _insert_searchable("limited alpha")
        await _insert_searchable("limited beta")

        items = await SearchableTestEntity.search().text("label", "limited").limit(1).to_list()

        assert len(items) == 1

    async def it_excludes_a_document_matching_a_filter_not_equals_clause() -> None:
        excluded = await _insert_searchable("excludable alpha")
        await _insert_searchable("excludable beta")

        items = await (
            SearchableTestEntity.search().text("label", "excludable").filter_not_equals("_id", excluded.id).to_list()
        )

        assert [item.label for item in items] == ["excludable beta"]


@pytest.mark.asyncio(loop_scope="session")
def describe_filter_in() -> None:
    async def it_restricts_results_to_the_given_ids() -> None:
        first = await _insert_searchable("filterable alpha")
        await _insert_searchable("filterable beta")

        items = await SearchableTestEntity.search().filter_in("_id", [first.id]).text("label", "filterable").to_list()

        assert [item.id for item in items] == [first.id]


@pytest.mark.asyncio(loop_scope="session")
def describe_should() -> None:
    async def it_matches_a_document_from_either_should_clause() -> None:
        first = await _insert_searchable("should first")
        second = await _insert_searchable("should second")
        await _insert_searchable("should excluded")

        items = await (
            SearchableTestEntity.search()
            .should(
                {"in": {"path": "_id", "value": [first.id]}},
                SearchableTestEntity.search().filter_equals("_id", second.id),
            )
            .to_list()
        )

        assert {item.id for item in items} == {first.id, second.id}


@pytest.mark.asyncio(loop_scope="session")
def describe_paginate() -> None:
    async def it_returns_a_page_of_matching_entities_with_total_items() -> None:
        for i in range(3):
            await _insert_searchable(f"paginated book {i}", genre="fantasy")

        page = await SearchableTestEntity.search().text("label", "paginated").paginate(1, 2)

        assert page["total_items"] == 3
        assert len(page["items"]) == 2

    async def it_returns_scored_items_when_scored_is_called() -> None:
        await _insert_searchable("scored page book", genre="sci-fi")

        page = await SearchableTestEntity.search().text("label", "scored").scored().paginate(1, 10)

        assert len(page["items"]) == 1
        assert isinstance(page["items"][0], Scored)
        assert page["items"][0].score > 0

    async def it_returns_facet_buckets_when_facet_was_added() -> None:
        await _insert_searchable("bucketed fantasy book", genre="fantasy")
        await _insert_searchable("bucketed scifi book", genre="sci-fi")

        page = await (
            SearchableTestEntity.search()
            .text("label", "bucketed")
            .facet("genreFacet", "genre", "string")
            .paginate(1, 10)
        )

        facets = page.get("facets", {})
        buckets = {bucket["_id"]: bucket["count"] for bucket in facets["genreFacet"]}
        assert buckets == {"fantasy": 1, "sci-fi": 1}

    async def it_omits_facets_from_the_page_when_no_facet_was_configured() -> None:
        await _insert_searchable("no facet book", genre="fantasy")

        page = await SearchableTestEntity.search().text("label", "no facet").paginate(1, 10)

        assert "facets" not in page


@pytest.mark.asyncio(loop_scope="session")
def describe_through_a_link() -> None:
    async def it_searches_the_link_targets_index_scoped_by_the_referencing_query() -> None:
        plain = await _insert_plain("plain-a")
        matching_target = await _insert_searchable("canterlot library", genre="fantasy")
        other_target = await _insert_searchable("canterlot archive", genre="fantasy")
        await _insert_linked("scope-a", matching_target, plain)
        await _insert_linked("scope-b", other_target, plain)

        query = LinkedTestEntity.find(LinkedTestEntity.label == "scope-a").search(LinkedTestEntity.target)
        assert isinstance(query, ForeignSearchQuery)

        items = await query.text("label", "library").to_list()

        assert len(items) == 1
        result = items[0]
        assert isinstance(result, LinkedTestEntity)
        assert result.label == "scope-a"
        assert isinstance(result.target, SearchableTestEntity)
        assert result.target.label == "canterlot library"

    async def it_returns_scored_results_when_scored_is_called() -> None:
        plain = await _insert_plain("plain-b")
        target = await _insert_searchable("scored link target", genre="fantasy")
        await _insert_linked("scope-scored", target, plain)

        items = await (
            LinkedTestEntity.find(LinkedTestEntity.label == "scope-scored")
            .search(LinkedTestEntity.target)
            .text("label", "scored")
            .scored()
            .to_list()
        )

        assert len(items) == 1
        assert isinstance(items[0], Scored)
        assert isinstance(items[0].item, LinkedTestEntity)
        assert isinstance(items[0].item.target, SearchableTestEntity)
        assert items[0].item.target.label == "scored link target"
        assert items[0].score > 0

    async def it_paginates_link_scoped_results_with_total_items() -> None:
        plain = await _insert_plain("plain-c")
        for i in range(3):
            target = await _insert_searchable(f"paginated link target {i}", genre="fantasy")
            await _insert_linked("scope-paginated", target, plain)

        page = await (
            LinkedTestEntity.find(LinkedTestEntity.label == "scope-paginated")
            .search(LinkedTestEntity.target)
            .text("label", "paginated")
            .paginate(1, 2)
        )

        assert page["total_items"] == 3
        assert len(page["items"]) == 2
        assert all(isinstance(item, LinkedTestEntity) for item in page["items"])
        assert all(isinstance(item.target, SearchableTestEntity) for item in page["items"])

    async def it_paginates_a_scored_page_with_facets() -> None:
        plain = await _insert_plain("plain-e")
        fantasy_target = await _insert_searchable("faceted fantasy target", genre="fantasy")
        scifi_target = await _insert_searchable("faceted scifi target", genre="sci-fi")
        await _insert_linked("scope-faceted", fantasy_target, plain)
        await _insert_linked("scope-faceted", scifi_target, plain)

        page = await (
            LinkedTestEntity.find(LinkedTestEntity.label == "scope-faceted")
            .search(LinkedTestEntity.target)
            .text("label", "faceted")
            .facet("genreFacet", "genre", "string")
            .scored()
            .paginate(1, 10)
        )

        assert page["total_items"] == 2
        assert len(page["items"]) == 2
        for item in page["items"]:
            assert isinstance(item, Scored)
            assert isinstance(item.item, LinkedTestEntity)
            assert isinstance(item.item.target, SearchableTestEntity)
        facets = page.get("facets", {})
        buckets = {bucket["_id"]: bucket["count"] for bucket in facets["genreFacet"]}
        assert buckets == {"fantasy": 1, "sci-fi": 1}

    async def it_returns_an_empty_list_when_the_scope_matches_nothing() -> None:
        items = await (
            LinkedTestEntity.find(LinkedTestEntity.label == "no-such-scope")
            .search(LinkedTestEntity.target)
            .text("label", "anything")
            .to_list()
        )

        assert items == []

    async def it_returns_an_empty_page_when_the_scope_matches_nothing() -> None:
        page = await (
            LinkedTestEntity.find(LinkedTestEntity.label == "no-such-scope")
            .search(LinkedTestEntity.target)
            .text("label", "anything")
            .paginate(1, 10)
        )

        assert page == {"items": [], "total_items": 0}

    async def it_raises_not_a_link_field_error_when_the_field_is_not_a_link() -> None:
        with pytest.raises(NotALinkFieldError):
            LinkedTestEntity.find(LinkedTestEntity.label == "scope-a").search(LinkedTestEntity.label)

    async def it_raises_entity_not_searchable_error_when_the_link_target_has_no_search_index() -> None:
        with pytest.raises(EntityNotSearchableError):
            LinkedTestEntity.find(LinkedTestEntity.label == "scope-a").search(LinkedTestEntity.unsearchable_target)

    async def it_supports_searching_from_a_find_one_scope() -> None:
        plain = await _insert_plain("plain-d")
        target = await _insert_searchable("find one link target", genre="fantasy")
        await _insert_linked("scope-find-one", target, plain)

        query = LinkedTestEntity.find_one(LinkedTestEntity.label == "scope-find-one").search(LinkedTestEntity.target)
        assert isinstance(query, ForeignSearchQuery)

        items = await query.text("label", "find one").to_list()

        assert len(items) == 1
        assert isinstance(items[0].target, SearchableTestEntity)
        assert items[0].target.label == "find one link target"

    async def it_caps_owner_resolution_to_one_when_scoped_from_a_find_one_query() -> None:
        plain = await _insert_plain("plain-f")
        first_target = await _insert_searchable("find one capped target a", genre="fantasy")
        second_target = await _insert_searchable("find one capped target b", genre="fantasy")
        await _insert_linked("scope-find-one-multi", first_target, plain)
        await _insert_linked("scope-find-one-multi", second_target, plain)

        query = LinkedTestEntity.find_one(LinkedTestEntity.label == "scope-find-one-multi").search(
            LinkedTestEntity.target
        )
        items = await query.text("label", "capped").to_list()

        assert len(items) == 1


@pytest.mark.asyncio(loop_scope="session")
def describe_mongo_scoped_self_search() -> None:
    async def it_searches_own_index_scoped_by_the_find_querys_match() -> None:
        await _insert_searchable("fiction canterlot tale", category="fiction")
        await _insert_searchable("nonfiction canterlot tale", category="nonfiction")

        query = SearchableTestEntity.find(SearchableTestEntity.category == "fiction").search()
        assert isinstance(query, SearchQuery)
        assert not isinstance(query, ForeignSearchQuery)

        items = await query.text("label", "canterlot").to_list()

        assert [item.label for item in items] == ["fiction canterlot tale"]

    async def it_returns_scored_results_when_scored_is_called() -> None:
        await _insert_searchable("scored scoped tale", category="fiction")

        items = await (
            SearchableTestEntity.find(SearchableTestEntity.category == "fiction")
            .search()
            .text("label", "scored")
            .scored()
            .to_list()
        )

        assert len(items) == 1
        assert isinstance(items[0], Scored)
        assert items[0].item.label == "scored scoped tale"
        assert items[0].score > 0

    async def it_paginates_scoped_results_with_total_items() -> None:
        for i in range(3):
            await _insert_searchable(f"paginated scoped tale {i}", category="fiction")

        page = await (
            SearchableTestEntity.find(SearchableTestEntity.category == "fiction")
            .search()
            .text("label", "paginated")
            .paginate(1, 2)
        )

        assert page["total_items"] == 3
        assert len(page["items"]) == 2

    async def it_returns_an_empty_list_when_the_scope_matches_nothing() -> None:
        items = await (
            SearchableTestEntity.find(SearchableTestEntity.category == "no-such-category")
            .search()
            .text("label", "anything")
            .to_list()
        )

        assert items == []

    async def it_returns_an_empty_page_with_zero_bucket_facets_when_the_scope_matches_nothing() -> None:
        page = await (
            SearchableTestEntity.find(SearchableTestEntity.category == "no-such-category")
            .search()
            .text("label", "anything")
            .facet("genreFacet", "genre", "string")
            .paginate(1, 10)
        )

        assert page == {"items": [], "total_items": 0, "facets": {"genreFacet": []}}

    async def it_raises_entity_not_searchable_error_when_the_entity_has_no_search_index() -> None:
        with pytest.raises(EntityNotSearchableError):
            PlainTestEntity.find(PlainTestEntity.label == "no-such-label").search()


@pytest.mark.asyncio(loop_scope="session")
def describe_delete_query() -> None:
    async def it_does_not_require_a_search_index_for_a_plain_entity() -> None:
        entity = await PlainTestEntity(label="plain-delete").insert()

        await PlainTestEntity.find_one(PlainTestEntity.id == entity.id).delete()

        assert await PlainTestEntity.get(entity.id) is None

    async def it_leaves_a_deleted_document_unsearchable() -> None:
        entity = await SearchableTestEntity(label="delete-me").insert()

        await SearchableTestEntity.find_one(SearchableTestEntity.id == entity.id).delete()

        assert not await is_searchable(entity)

    async def it_does_not_require_a_batch_when_a_session_delete_matches_nothing(
        hoodie_client: AsyncMongoClient,
    ) -> None:
        async with hoodie_client.start_session() as session:
            result = await SearchableTestEntity.find(
                SearchableTestEntity.label == "no-such-label",
                session=session,
            ).delete(session=session)

        assert result is not None
        assert result.deleted_count == 0

    async def it_raises_when_a_session_delete_has_no_active_batch(hoodie_client: AsyncMongoClient) -> None:
        entity = await SearchableTestEntity(label="unmanaged-delete").insert()

        async with hoodie_client.start_session() as session:
            with pytest.raises(UnmanagedSessionError):
                await SearchableTestEntity.find_one(
                    SearchableTestEntity.id == entity.id,
                    session=session,
                ).delete(session=session)
