from typing import Any

import pytest
from beanie import PydanticObjectId
from pydantic import BaseModel, ValidationError

from canterlot.emails.core.definitions import (
    EmailTaskPayload,
    EmailTemplate,
    SubBrand,
)
from tools.factories import EmailTaskPayloadFactory

CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439033")


class DummyPayloadModel(BaseModel):
    template: EmailTemplate


def describe_sub_brand():
    @pytest.mark.parametrize("brand", list(SubBrand))
    def it_formats_sender_string(brand: SubBrand):
        expected_sender = f"{brand.value.title()} · Canterlot <{brand.value}@noreply.canterlot.com.br>"

        assert brand.sender == expected_sender


def describe_email_template():
    def it_builds_template_path(random_template: EmailTemplate):
        expected_path = f"{random_template.brand}/{random_template.slug}.html.j2"

        assert random_template.template_path == expected_path

    def it_returns_all_registered_templates():
        all_templates = EmailTemplate.all()

        assert len(all_templates) == len(EmailTemplate._registry)
        assert len(all_templates) > 0

    def describe_pydantic_schema_validation():
        def it_validates_template_from_registered_name_string(random_template: EmailTemplate):
            model = DummyPayloadModel.model_validate({"template": random_template.name})
            assert model.template == random_template

        def it_validates_template_instance_directly(random_template: EmailTemplate):
            model = DummyPayloadModel.model_validate({"template": random_template})
            assert model.template == random_template

        def it_raises_error_for_unknown_template_name():
            with pytest.raises(ValidationError, match="Unknown email template: NON_EXISTENT_TEMPLATE"):
                DummyPayloadModel.model_validate({"template": "NON_EXISTENT_TEMPLATE"})

        def it_raises_error_for_invalid_input_type():
            with pytest.raises(ValidationError, match="Invalid input type for EmailTemplate"):
                DummyPayloadModel.model_validate({"template": 12345})


def describe_email_task_payload():
    def it_allows_valid_global_template_payload_without_club_id(global_template: EmailTemplate):
        payload = EmailTaskPayloadFactory.build(template=global_template)
        assert payload.club_id is None

    def it_allows_valid_club_preference_template_payload_with_club_id(club_template: EmailTemplate):
        payload = EmailTaskPayloadFactory.build(template=club_template, club_id=CLUB_ID)
        assert payload.club_id == CLUB_ID

    def it_raises_error_when_global_template_is_given_a_club_id(global_template: EmailTemplate):
        with pytest.raises(ValueError, match="Cannot attach club_id to global template"):
            EmailTaskPayloadFactory.build(template=global_template, club_id=CLUB_ID)

    def it_raises_error_when_club_preference_template_is_missing_club_id(club_template: EmailTemplate):
        with pytest.raises(ValueError, match="requires a club_id"):
            EmailTaskPayloadFactory.build(template=club_template, club_id=None)

    def it_recoerces_context_into_its_concrete_schema_after_a_json_round_trip(global_template: EmailTemplate):
        original = EmailTaskPayloadFactory.build(template=global_template)

        roundtripped = EmailTaskPayload[Any].model_validate_json(original.model_dump_json())

        assert isinstance(roundtripped.context, global_template.context_schema)
        assert roundtripped.context == original.context

    def it_leaves_an_already_hydrated_context_untouched():
        payload = EmailTaskPayloadFactory.build()
        assert not isinstance(payload.context, dict)

    def it_skips_coercion_when_the_template_itself_fails_to_resolve():
        with pytest.raises(ValidationError, match="Unknown email template"):
            EmailTaskPayload.model_validate(
                {
                    "template": "NON_EXISTENT_TEMPLATE",
                    "to": "twilight@canterlot.dev",
                    "context": {"some": "dict"},
                }
            )
