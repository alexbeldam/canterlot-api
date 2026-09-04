from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic.networks import HttpUrl

from canterlot.emails import EmailTemplate, RenderedEmailTemplate, Templates, render_email_template
from canterlot.emails.core import schemas
from tools.factories import BaseContextFactory
from tools.factories.emails import SpikeRoleContextFactory


@pytest.fixture
def mock_jinja_env():
    with patch("canterlot.emails.core.renderer._ENV") as mock_env:
        mock_jinja_template = MagicMock()
        mock_jinja_template.render.return_value = "<html>Rendered Email Body</html>"
        mock_env.get_template.return_value = mock_jinja_template
        yield mock_env, mock_jinja_template


def describe_render_email_template():
    def it_renders_full_email_template_successfully(mock_jinja_env, random_template: EmailTemplate[Any]):
        mock_env, mock_jinja_template = mock_jinja_env

        context = BaseContextFactory.build_for_template(
            random_template,
            unsubscribe_url=HttpUrl("https://canterlot.com.br/unsubscribe"),
        )

        result = render_email_template(random_template, context)

        assert isinstance(result, RenderedEmailTemplate)
        assert result.html == "<html>Rendered Email Body</html>"
        assert result.sender == random_template.brand.sender
        assert result.reply_to == "sunset@canterlot.com.br"
        assert result.headers == {
            "List-Unsubscribe": "<mailto:sunset@canterlot.com.br?subject=unsubscribe>, <https://canterlot.com.br/unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

        mock_env.get_template.assert_called_once_with(random_template.template_path)

        called_context = mock_jinja_template.render.call_args[0][0]
        assert called_context["preheader"] == result.subject
        assert called_context["heading"] == (random_template.heading_template or result.subject)

    def it_raises_value_error_when_subject_string_formatting_fails(
        mock_jinja_env,  # noqa: ARG001
        template_with_formatted_subject: EmailTemplate[Any],
    ):
        mock_context = MagicMock(spec=schemas.BaseEmailContext)
        mock_context.model_dump.return_value = {}

        with pytest.raises(ValueError) as exc_info:
            render_email_template(template_with_formatted_subject, mock_context)

        assert f"email template '{template_with_formatted_subject.name}'" in str(exc_info.value)

    def it_omits_headers_if_unsubscribe_url_is_none_or_missing(mock_jinja_env, random_template: EmailTemplate[Any]):  # noqa: ARG001
        context = BaseContextFactory.build_for_template(
            random_template,
            unsubscribe_url=None,
        )

        result = render_email_template(random_template, context)
        assert result.headers is None

    def it_uses_a_stable_heading_when_the_template_overrides_it(mock_jinja_env):
        _, mock_jinja_template = mock_jinja_env
        template = cast(Any, Templates.CELESTIA_VERIFY_EMAIL)
        context = BaseContextFactory.build_for_template(template)

        result = render_email_template(template, context)

        assert result.subject != "Confirm your email on Canterlot"
        called_context = mock_jinja_template.render.call_args[0][0]
        assert called_context["heading"] == "Confirm your email on Canterlot"
        assert called_context["preheader"] == result.subject

    @pytest.mark.integration
    @pytest.mark.parametrize("template", EmailTemplate.all())
    def it_successfully_renders_all_configured_templates(template: EmailTemplate[Any]):
        context_instance = BaseContextFactory.build_for_template(template)

        result = render_email_template(template, context_instance)

        assert result.subject is not None
        assert isinstance(result.html, str)
        assert "<html>" in result.html or "<!DOCTYPE" in result.html

    def it_renders_promotion_text_correctly():
        template = cast(Any, Templates.SPIKE_ROLE_CHANGED)
        context = SpikeRoleContextFactory.build(is_promotion=True)

        result = render_email_template(template, context)
        assert "This gives you access to more club management tools." in result.html
        assert "Your administrative permissions" not in result.html

    def it_renders_demotion_text_correctly():
        template = cast(Any, Templates.SPIKE_ROLE_CHANGED)
        context = SpikeRoleContextFactory.build(is_promotion=False)

        result = render_email_template(template, context)
        assert "Your administrative permissions for this club have been modified." in result.html
        assert "This gives you access to more club" not in result.html


def describe_rendered_email_template():
    def it_converts_to_email_message_with_single_and_multiple_recipients(
        mock_jinja_env,  # noqa: ARG001
        random_template: EmailTemplate[Any],
    ):
        context = BaseContextFactory.build_for_template(random_template)

        result = render_email_template(random_template, context)

        msg_single = result.to_message("twilight@canterlot.com.br")
        assert msg_single.to == ["twilight@canterlot.com.br"]
        assert msg_single.subject == result.subject

        msg_list = result.to_message(["twilight@canterlot.com.br", "spike@canterlot.com.br"])
        assert msg_list.to == ["twilight@canterlot.com.br", "spike@canterlot.com.br"]

    def it_omits_headers_if_unsubscribe_url_is_invalid(mock_jinja_env, random_template: EmailTemplate[Any]):  # noqa: ARG001
        context = BaseContextFactory.build_for_template(random_template, unsubscribe_url=None)

        result = render_email_template(random_template, context)

        assert result.headers is None
