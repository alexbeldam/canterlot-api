from beanie.exceptions import DocumentWasNotSaved

from canterlot.hoodie.exceptions import (
    EntityLinkWithoutIdError,
    EntityNotSearchableError,
    HoodieError,
    HoodieNotInitializedError,
    InvalidSessionTypeError,
    ProxiedMethodNotImplementedError,
    SearchIndexNeverQueryableError,
    SearchWithinTransactionError,
    UnsupportedSearchableFieldError,
)
from tests.hoodie.entities import PlainTestEntity


def describe_invalid_session_type_error() -> None:
    def it_reports_the_actual_type_of_the_bad_session_value() -> None:
        error = InvalidSessionTypeError("not-a-session")

        assert error.session == "not-a-session"
        assert error.actual_type == "str"
        assert "str" in str(error)


def describe_hoodie_not_initialized_error() -> None:
    def it_explains_that_no_entities_are_registered() -> None:
        error = HoodieNotInitializedError()

        assert "not been initialized" in str(error)


def describe_search_index_never_queryable_error() -> None:
    def it_names_the_index_that_never_became_queryable() -> None:
        error = SearchIndexNeverQueryableError("some_search_index")

        assert error.index_name == "some_search_index"
        assert "some_search_index" in str(error)


def describe_proxied_method_not_implemented_error() -> None:
    def it_names_the_class_and_method_that_have_no_implementation() -> None:
        error = ProxiedMethodNotImplementedError(PlainTestEntity, "frobnicate")

        assert error.target_cls is PlainTestEntity
        assert error.name == "frobnicate"
        assert "frobnicate" in str(error)


def describe_search_within_transaction_error() -> None:
    def it_names_the_index_the_search_was_attempted_against() -> None:
        error = SearchWithinTransactionError("some_search_index")

        assert error.index_name == "some_search_index"
        assert "some_search_index" in str(error)


def describe_entity_link_without_id_error() -> None:
    def it_names_the_entity_whose_document_has_no_id() -> None:
        error = EntityLinkWithoutIdError(PlainTestEntity)

        assert error.entity is PlainTestEntity
        assert "PlainTestEntity" in str(error)

    def it_is_both_a_hoodie_error_and_a_beanie_document_was_not_saved_error() -> None:
        error = EntityLinkWithoutIdError(PlainTestEntity)

        assert isinstance(error, HoodieError)
        assert isinstance(error, DocumentWasNotSaved)


def describe_entity_not_searchable_error() -> None:
    def it_names_the_entity_with_no_search_index() -> None:
        error = EntityNotSearchableError(PlainTestEntity)

        assert error.entity is PlainTestEntity
        assert "PlainTestEntity" in str(error)


def describe_unsupported_searchable_field_error() -> None:
    def it_omits_the_reason_clause_when_none_is_given() -> None:
        error = UnsupportedSearchableFieldError(
            entity=PlainTestEntity,
            field_name="label",
            annotation=int,
        )

        assert error.reason is None
        assert str(error) == (
            "Searchable field 'label' on entity 'PlainTestEntity' has an unsupported type <class 'int'>."
        )

    def it_appends_the_reason_clause_when_one_is_given() -> None:
        error = UnsupportedSearchableFieldError(
            entity=PlainTestEntity,
            field_name="label",
            annotation=int,
            reason="Ints are not supported.",
        )

        assert error.reason == "Ints are not supported."
        assert str(error).endswith("Ints are not supported.")
