from __future__ import annotations

import warnings
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from canterlot.hoodie import Entity
from canterlot.hoodie.exceptions import (
    DuplicateSearchIndexError,
    EmptySearchIndexNameError,
    UnexpectedSearchableFieldError,
    UnsupportedSearchableFieldError,
)
from canterlot.hoodie.fields import (
    Searchable,
    SearchableField,
    SearchableType,
    TypeResolver,
    get_searchable_fields,
    register_type_resolver,
    searchable,
)


class _CycleNodeA(BaseModel):
    child: _CycleNodeB | None = None


class _CycleNodeB(BaseModel):
    child: _CycleNodeA | None = None


_CycleNodeA.model_rebuild()
_CycleNodeB.model_rebuild()


class _CyclicTestEntity(Entity):
    root: _CycleNodeA = _CycleNodeA()

    class Settings:
        name = "hoodie_test_cyclic_entities"


class _ZeroDomainFieldTestEntity(Entity):
    label: str = "default"

    class Settings:
        name = "hoodie_test_zero_domain_field_entities"
        search_index = "hoodie_test_zero_domain_field_index"


class _DefaultIdTestEntity(Entity):
    label: str = "default"

    class Settings:
        name = "hoodie_test_default_id_entities"


class _StrIdTestEntity(Entity):
    id: str = Field(default_factory=lambda: "str-id", alias="_id")  # type: ignore[assignment]
    label: str = "default"

    class Settings:
        name = "hoodie_test_str_id_entities"


class _IntIdTestEntity(Entity):
    id: int = Field(default_factory=lambda: 1, alias="_id")  # type: ignore[assignment]
    label: str = "default"

    class Settings:
        name = "hoodie_test_int_id_entities"


def describe_searchable_field() -> None:
    def it_defaults_its_path_to_its_own_name_when_none_is_given() -> None:
        field = SearchableField(name="title", type=SearchableType.STRING, config=Searchable())

        assert field.path == "title"

    def it_extracts_none_when_a_dotted_path_traverses_through_a_none_value() -> None:
        field = SearchableField(name="bio", type=SearchableType.STRING, config=Searchable(), path="profile.bio")

        assert field.extract_value(SimpleNamespace(profile=None)) is None

    def it_returns_a_bare_mapping_for_a_non_facetable_field() -> None:
        field = SearchableField(name="title", type=SearchableType.STRING, config=Searchable())

        mapping = field.to_atlas_mapping()

        assert mapping == {"type": "string", "analyzer": "lucene.standard"}

    def it_adds_an_exact_match_keyword_submapping_for_a_facetable_field() -> None:
        field = SearchableField(name="title", type=SearchableType.STRING, config=Searchable(facetable=True))

        mapping = field.to_atlas_mapping()

        assert isinstance(mapping, list)
        string_mapping = next(entry for entry in mapping if entry["type"] == "string")
        assert string_mapping["multi"]["keyword"] == {"type": "string", "analyzer": "lucene.keyword"}

    def it_adds_a_string_facet_type_alongside_the_analyzed_mapping_for_a_facetable_field() -> None:
        field = SearchableField(name="title", type=SearchableType.STRING, config=Searchable(facetable=True))

        mapping = field.to_atlas_mapping()

        assert isinstance(mapping, list)
        assert {"type": "stringFacet"} in mapping


def describe_get_searchable_fields() -> None:
    def it_terminates_for_a_mutually_recursive_nested_model_shape_instead_of_hanging() -> None:
        # If this file imports at all, the class body above already ran this once; a BFS
        # with no cycle guard would never return, hanging module import itself.
        fields = get_searchable_fields(_CyclicTestEntity)

        assert {f.name for f in fields} == {"_id"}

    def it_returns_only_the_id_field_when_an_entity_has_no_domain_searchable_fields() -> None:
        fields = get_searchable_fields(_ZeroDomainFieldTestEntity)

        assert {f.name for f in fields} == {"_id"}

    def it_resolves_the_id_field_as_an_atlas_objectid_by_default() -> None:
        fields = get_searchable_fields(_DefaultIdTestEntity)

        id_field = next(f for f in fields if f.name == "_id")
        assert id_field.resolved_atlas_type == "objectId"

    def it_resolves_the_id_field_as_an_atlas_string_for_a_str_id_override() -> None:
        fields = get_searchable_fields(_StrIdTestEntity)

        id_field = next(f for f in fields if f.name == "_id")
        assert id_field.resolved_atlas_type == "string"

    def it_resolves_the_id_field_as_an_atlas_number_for_an_int_id_override() -> None:
        fields = get_searchable_fields(_IntIdTestEntity)

        id_field = next(f for f in fields if f.name == "_id")
        assert id_field.resolved_atlas_type == "number"


def describe_get_searchable_fields_with_an_unsupported_id_type() -> None:
    def it_raises_for_an_id_type_with_no_registered_atlas_mapping() -> None:
        # Overriding `id` makes pydantic warn that it "shadows" Document's own attribute;
        # expected and harmless, not worth failing the zero-warnings policy over.
        with pytest.raises(UnsupportedSearchableFieldError), warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)

            class _FloatIdTestEntity(Entity):
                id: float = Field(default_factory=lambda: 1.0, alias="_id")  # type: ignore[assignment]
                label: str = searchable(default="default")

                class Settings:
                    name = "hoodie_test_float_id_entities"
                    search_index = "hoodie_test_float_id_index"


def describe_get_searchable_fields_with_an_unsupported_domain_field_type() -> None:
    def it_raises_for_a_bare_scalar_type_that_isnt_a_string() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _IntFieldTestEntity(Entity):
                visit_count: int = searchable(default=0)

                class Settings:
                    name = "hoodie_test_int_field_entities"
                    search_index = "hoodie_test_int_field_index"

    def it_raises_for_a_mapping_type() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _MappingFieldTestEntity(Entity):
                labels: dict[str, str] = searchable(default_factory=dict)

                class Settings:
                    name = "hoodie_test_mapping_field_entities"
                    search_index = "hoodie_test_mapping_field_index"

    def it_raises_for_an_untyped_bare_container() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _BareListFieldTestEntity(Entity):
                items: list = searchable(default_factory=list)  # type: ignore[type-arg]

                class Settings:
                    name = "hoodie_test_bare_list_field_entities"
                    search_index = "hoodie_test_bare_list_field_index"

    def it_raises_for_a_typed_container_with_no_type_arguments() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _EmptyTupleFieldTestEntity(Entity):
                pair: tuple[()] = searchable(default=())

                class Settings:
                    name = "hoodie_test_empty_tuple_field_entities"
                    search_index = "hoodie_test_empty_tuple_field_index"

    def it_raises_for_a_union_of_more_than_one_non_none_type() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _ComplexUnionFieldTestEntity(Entity):
                value: str | int = searchable(default="default")

                class Settings:
                    name = "hoodie_test_complex_union_field_entities"
                    search_index = "hoodie_test_complex_union_field_index"

    def it_raises_for_a_fixed_size_tuple_with_a_non_string_member() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _MixedTupleFieldTestEntity(Entity):
                pair: tuple[str, int] = searchable()

                class Settings:
                    name = "hoodie_test_mixed_tuple_field_entities"
                    search_index = "hoodie_test_mixed_tuple_field_index"

    def it_raises_for_a_list_of_a_non_string_type() -> None:
        with pytest.raises(UnsupportedSearchableFieldError):

            class _IntListFieldTestEntity(Entity):
                counts: list[int] = searchable(default_factory=list)

                class Settings:
                    name = "hoodie_test_int_list_field_entities"
                    search_index = "hoodie_test_int_list_field_index"


class _Profile(BaseModel):
    bio: str = "default"
    tagline: str = "default"


def describe_get_searchable_fields_with_a_supported_domain_field_type() -> None:
    def it_resolves_multiple_field_type_variations_on_one_entity() -> None:
        class _BoolResolver(TypeResolver):
            def resolve(self, annotation: Any) -> SearchableType | None:
                return SearchableType.STRING if annotation is bool else None

        register_type_resolver(_BoolResolver(), prepend=False)

        class _MultiTypeFieldTestEntity(Entity):
            pair: tuple[str, str] = searchable()
            flag: bool = searchable(default=False)
            profile: _Profile = _Profile()
            label: str = searchable(default="default")

            class Settings:
                name = "hoodie_test_multi_type_field_entities"
                search_index = "hoodie_test_multi_type_field_index"

        fields = get_searchable_fields(_MultiTypeFieldTestEntity)

        pair_field = next(f for f in fields if f.name == "pair")
        assert pair_field.type is SearchableType.STRING_LIST

        flag_field = next(f for f in fields if f.name == "flag")
        assert flag_field.type is SearchableType.STRING

        assert {f.name for f in fields} == {"_id", "pair", "flag", "label"}


def describe_entity_registration_invariants() -> None:
    def it_rejects_a_blank_search_index_name() -> None:
        with pytest.raises(EmptySearchIndexNameError):

            class _BlankSearchIndexTestEntity(Entity):
                label: str = searchable(default="default")

                class Settings:
                    name = "hoodie_test_blank_search_index_entities"
                    search_index = "   "

    def it_rejects_searchable_fields_with_no_search_index_configured() -> None:
        with pytest.raises(UnexpectedSearchableFieldError):

            class _UnindexedSearchableTestEntity(Entity):
                label: str = searchable(default="default")

                class Settings:
                    name = "hoodie_test_unindexed_searchable_entities"

    def it_rejects_a_second_entity_reusing_an_already_registered_search_index() -> None:
        class _FirstIndexOwnerTestEntity(Entity):
            label: str = searchable(default="default")

            class Settings:
                name = "hoodie_test_first_index_owner_entities"
                search_index = "hoodie_test_shared_duplicate_index"

        with pytest.raises(DuplicateSearchIndexError):

            class _SecondIndexOwnerTestEntity(Entity):
                label: str = searchable(default="default")

                class Settings:
                    name = "hoodie_test_second_index_owner_entities"
                    search_index = "hoodie_test_shared_duplicate_index"
