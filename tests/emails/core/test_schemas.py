import pytest
from pydantic import HttpUrl, ValidationError

from canterlot.emails.core.schemas import (
    LunaOwnershipReclaimedContext,
    LunaProviderActionContext,
    SpikeRoleContext,
    VerificationContext,
)
from canterlot.types import AuthProviderName, MemberRole


def describe_verification_context_constraints():
    @pytest.mark.parametrize(
        "invalid_code",
        [
            "1234567",  # Too short
            "123456789",  # Too long
            "1234-567",  # Contains special characters
            "ABC!1234",  # Contains special characters
            "        ",  # Only spaces
        ],
    )
    def it_rejects_malformed_verification_codes(invalid_code):
        with pytest.raises(ValidationError):
            VerificationContext(
                recipient_name="Twilight", code=invalid_code, action_url=HttpUrl("https://canterlot.com.br/verify")
            )

    def it_accepts_and_automatically_capitalizes_mixed_case_eight_char_codes():
        context = VerificationContext(
            recipient_name="Twilight",
            code="a1b2c3d4",
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert context.code == "A1B2C3D4"


def describe_oauth_provider_formatting():
    def it_accepts_valid_enum_values_and_formats_them_to_title_case():
        context = LunaProviderActionContext(
            recipient_name="Twilight",
            provider_name=AuthProviderName.GOOGLE,
            action_url=HttpUrl("https://canterlot.com.br/security"),
        )
        dumped = context.model_dump(mode="json")
        assert dumped["provider_name"] == "Google"

    def it_rejects_unsupported_provider_names():
        with pytest.raises(ValidationError):
            LunaProviderActionContext(
                recipient_name="Twilight",
                provider_name="FACEBOOK",
                action_url=HttpUrl("https://canterlot.com.br/security"),
            )


def describe_member_role_formatting():
    @pytest.mark.parametrize(
        "role, expected_title",
        [
            (MemberRole.OWNER, "Owner"),
            (MemberRole.ADMIN, "Admin"),
            (MemberRole.MEMBER, "Member"),
        ],
    )
    def it_formats_roles_to_title_case(role, expected_title):
        context = SpikeRoleContext(
            recipient_name="Twilight",
            club_name="Canterlot Book Club",
            action_url=HttpUrl("https://canterlot.com.br/club"),
            notifications_url=HttpUrl("https://canterlot.com.br/notifications"),
            role_name=role,
        )
        dumped = context.model_dump(mode="json")
        assert dumped["role_name"] == expected_title

    def it_cascades_role_formatting_across_deep_inheritance_chains():
        context = LunaOwnershipReclaimedContext(
            recipient_name="Twilight",
            actor_name="Princess Celestia",
            club_name="Canterlot Court",
            action_url=HttpUrl("https://canterlot.com.br/club"),
            role_name=MemberRole.ADMIN,
        )
        dumped = context.model_dump(mode="json")
        assert dumped["role_name"] == "Admin"


def describe_string_constraints():
    @pytest.mark.parametrize("whitespace_string", ["", "   ", "\n", "\t"])
    def it_rejects_empty_or_whitespace_only_strings_for_required_fields(whitespace_string):
        with pytest.raises(ValidationError):
            VerificationContext(
                recipient_name=whitespace_string, code="A1B2C3D4", action_url=HttpUrl("https://canterlot.com.br/verify")
            )

    def it_strips_leading_and_trailing_whitespace_from_valid_strings():
        context = VerificationContext(
            recipient_name="  Twilight Sparkle  ",
            code="A1B2C3D4",
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert context.recipient_name == "Twilight Sparkle"


def describe_url_security_constraints():
    @pytest.mark.parametrize(
        "unsecure_url",
        [
            "http://canterlot.com.br/unsubscribe",
            "ftp://canterlot.com.br/files",
        ],
    )
    def it_rejects_non_https_protocols(unsecure_url):
        with pytest.raises(ValidationError):
            VerificationContext(
                recipient_name="Twilight",
                code="A1B2C3D4",
                action_url=unsecure_url,  # type: ignore
            )
