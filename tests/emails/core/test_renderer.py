from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic.networks import HttpUrl

from canterlot.emails import EmailTemplate, RenderedEmailTemplate, render_email_template
from canterlot.emails.core.schemas import SpikeBookContext, VerificationContext
from canterlot.types import AuthProviderName, MemberRole


@pytest.fixture
def mock_jinja_env():
    with patch("canterlot.emails.core.renderer._ENV") as mock_env:
        mock_jinja_template = MagicMock()
        mock_jinja_template.render.return_value = "<html>Rendered Email Body</html>"
        mock_env.get_template.return_value = mock_jinja_template
        yield mock_env, mock_jinja_template


def describe_render_email_template():
    def it_renders_full_email_template_successfully(mock_jinja_env):
        mock_env, mock_jinja_template = mock_jinja_env
        template = EmailTemplate.SPIKE_BOOK_DECIDED
        context = {
            "recipient_name": "Twilight Sparkle",
            "club_name": "Ponyville Book Club",
            "book_title": "Daring Do",
            "action_url": "https://canterlot.com.br/round",
            "unsubscribe_url": "https://canterlot.com.br/unsubscribe",
            "notifications_url": "https://canterlot.com.br/notifications",
        }

        result = render_email_template(template, context)

        assert isinstance(result, RenderedEmailTemplate)
        assert result.subject == "Ponyville Book Club: time to start reading Daring Do"
        assert result.html == "<html>Rendered Email Body</html>"
        assert result.sender == template.brand.sender
        assert result.reply_to == "sunset@canterlot.com.br"

        # Verifies preferences-enabled brands inject unsubscription headers
        assert result.headers == {
            "List-Unsubscribe": "<mailto:sunset@canterlot.com.br?subject=unsubscribe>, <https://canterlot.com.br/unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

        mock_env.get_template.assert_called_once_with(template.template_path)

        # Ensure injected metadata context translates down to Jinja cleanly
        called_context = mock_jinja_template.render.call_args[0][0]
        assert called_context["preheader"] == result.subject
        assert called_context["heading"] == result.subject

    def it_accepts_a_pre_validated_pydantic_model_directly(mock_jinja_env):
        _, mock_jinja_template = mock_jinja_env
        template = EmailTemplate.CELESTIA_VERIFY_EMAIL

        model_context = VerificationContext(
            recipient_name="Twilight",
            code="ABC12345",
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )

        result = render_email_template(template, model_context)

        assert result.subject == "Confirm your email on Canterlot"
        called_context = mock_jinja_template.render.call_args[0][0]
        assert called_context["code"] == "ABC12345"

    def it_raises_pydantic_validation_error_when_context_is_missing_fields(mock_jinja_env):  # noqa: ARG001
        template = EmailTemplate.SPIKE_BOOK_DECIDED
        incomplete_context = {"club_name": "Ponyville Book Club"}

        with pytest.raises(ValidationError):
            render_email_template(template, incomplete_context)

    def it_raises_value_error_when_subject_string_formatting_fails(mock_jinja_env):  # noqa: ARG001
        template = EmailTemplate.SPIKE_BOOK_DECIDED

        class BrokenContext(SpikeBookContext):
            pass

        with patch.object(template, "context_schema") as mock_schema:
            mock_schema.return_value.model_dump.return_value = {
                "unsubscribe_url": "https://canterlot.com.br/unsubscribe",
                "club_name": "Ponyville Book Club",
                "action_url": "https://canterlot.com.br/round",
            }

            with pytest.raises(ValueError) as exc_info:
                render_email_template(template, {})

            assert "Missing 'book_title' for subject in email template 'SPIKE_BOOK_DECIDED'" in str(exc_info.value)

    def it_omits_headers_if_sub_brand_does_not_include_preferences(mock_jinja_env):  # noqa: ARG001
        template = EmailTemplate.CELESTIA_INVITE_EXTERNAL
        context = {
            "inviter_name": "Celestia",
            "club_name": "Canterlot Royal Court",
            "action_url": "https://canterlot.com.br/join",
            "unsubscribe_url": "https://canterlot.com.br/unsubscribe",
        }

        result = render_email_template(template, context)
        assert result.headers is None

    @pytest.mark.integration
    @pytest.mark.parametrize("template", list(EmailTemplate))
    def it_successfully_renders_all_configured_templates(template):
        mock_data = {}

        for field_name, field_info in template.context_schema.model_fields.items():
            if field_info.default is not None and not field_info.is_required():
                mock_data[field_name] = field_info.default
                continue

            if "url" in field_name:
                mock_data[field_name] = f"https://canterlot.com.br/mock-{field_name}"
            elif "code" in field_name:
                mock_data[field_name] = "CODE1234"
            elif "role" in field_name:
                mock_data[field_name] = MemberRole.MEMBER
            elif "provider" in field_name:
                mock_data[field_name] = AuthProviderName.GOOGLE
            else:
                mock_data[field_name] = f"mock_{field_name}"

        result = render_email_template(template, mock_data)

        assert result.subject is not None
        assert isinstance(result.html, str)
        assert "<html>" in result.html or "<!DOCTYPE" in result.html

    def it_renders_promotion_text_correctly():
        template = EmailTemplate.SPIKE_ROLE_CHANGED
        context = {
            "recipient_name": "Twilight Sparkle",
            "club_name": "Ponyville Book Club",
            "role_name": MemberRole.ADMIN,
            "is_promotion": True,
            "action_url": "https://canterlot.com.br/club",
            "notifications_url": "https://canterlot.com.br/notifications",
        }

        result = render_email_template(template, context)
        assert "This gives you access to more club management tools." in result.html
        assert "Your administrative permissions" not in result.html

    def it_renders_demotion_text_correctly():
        template = EmailTemplate.SPIKE_ROLE_CHANGED
        context = {
            "recipient_name": "Twilight Sparkle",
            "club_name": "Ponyville Book Club",
            "role_name": MemberRole.MEMBER,
            "is_promotion": False,
            "action_url": "https://canterlot.com.br/club",
            "notifications_url": "https://canterlot.com.br/notifications",
        }

        result = render_email_template(template, context)
        assert "Your administrative permissions for this club have been modified." in result.html
        assert "This gives you access to more club" not in result.html


def describe_rendered_email_template():
    def it_converts_to_email_message_with_single_and_multiple_recipients(mock_jinja_env):  # noqa: ARG001
        template = EmailTemplate.SPIKE_BOOK_DECIDED
        context = {
            "recipient_name": "Twilight Sparkle",
            "club_name": "Ponyville Book Club",
            "book_title": "Daring Do",
            "action_url": "https://canterlot.com.br/round",
            "unsubscribe_url": "https://canterlot.com.br/unsubscribe",
            "notifications_url": "https://canterlot.com.br/notifications",
        }
        result = render_email_template(template, context)

        msg_single = result.to_message("twilight@canterlot.com.br")
        assert msg_single.to == ["twilight@canterlot.com.br"]
        assert msg_single.subject == result.subject

        msg_list = result.to_message(["twilight@canterlot.com.br", "spike@canterlot.com.br"])
        assert msg_list.to == ["twilight@canterlot.com.br", "spike@canterlot.com.br"]

    def it_omits_headers_if_brand_includes_preferences_but_unsubscribe_url_is_invalid(mock_jinja_env):  # noqa: ARG001
        template = EmailTemplate.SPIKE_BOOK_DECIDED

        with patch.object(template, "context_schema") as mock_schema:
            mock_schema.return_value.model_dump.return_value = {
                "recipient_name": "Twilight Sparkle",
                "club_name": "Ponyville Book Club",
                "book_title": "Daring Do",
                "action_url": "https://canterlot.com.br/round",
                "notifications_url": "https://canterlot.com.br/notifications",
                "unsubscribe_url": None,
            }

            result = render_email_template(template, {})
            assert result.headers is None
