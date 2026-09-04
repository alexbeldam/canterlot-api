import pytest
from beanie import PydanticObjectId
from pydantic import HttpUrl, ValidationError

from canterlot.config import get_settings
from canterlot.emails.core.enums import EmailCategory
from canterlot.emails.core.schemas import (
    AuthProviderContext,
    BaseVerificationContext,
    ClubActionContext,
    ClubActorActionContext,
    EmailVerificationContext,
    InviteExternalContext,
    InviteInternalContext,
    LunaProviderActionContext,
    PasswordChangedContext,
    PasswordResetValidationContext,
    RecipientContext,
    SpikeActionContext,
    SpikeBaseContext,
    SpikeBookContext,
    SpikeRoleContext,
)
from canterlot.types import AuthProviderName, MemberRole, secret_code_adapter
from tools.factories import ClubFactory, UserFactory

SOME_CODE = "123456"


def describe_verification_context_constraints():
    @pytest.mark.parametrize(
        "invalid_code",
        [
            "12345",  # Too short
            "1234567",  # Too long
            "1234-5",  # Contains special characters
            "ABCDEF",  # Contains letters
            "      ",  # Only spaces
        ],
    )
    def it_rejects_malformed_verification_codes(invalid_code):
        with pytest.raises(ValidationError):
            BaseVerificationContext(
                recipient_name="Twilight",
                code=invalid_code,
                action_url=HttpUrl("https://canterlot.com.br/verify"),
            )

    def it_accepts_six_digit_codes():
        context = BaseVerificationContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert context.code == SOME_CODE

    def it_raises_not_implemented_error_for_base_verification_expires_in_minutes():
        class DummyVerificationContext(BaseVerificationContext):
            pass

        ctx = DummyVerificationContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        with pytest.raises(NotImplementedError, match="Subclasses must define expires_in_minutes"):
            _ = ctx.expires_in_minutes


def describe_verification_expires_in_display():
    def it_formats_display_for_under_sixty_minutes():
        class MockMinutesContext(BaseVerificationContext):
            @property
            def expires_in_minutes(self) -> int:
                return 10

        ctx = MockMinutesContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert ctx.expires_in_display == "10 minutes"

    def it_formats_display_for_exact_single_or_multiple_hours():
        class MockHoursContext(BaseVerificationContext):
            @property
            def expires_in_minutes(self) -> int:
                return 60

        ctx1 = MockHoursContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert ctx1.expires_in_display == "1 hour"

        class MockMultiHoursContext(BaseVerificationContext):
            @property
            def expires_in_minutes(self) -> int:
                return 120

        ctx2 = MockMultiHoursContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert ctx2.expires_in_display == "2 hours"

    def it_formats_display_for_hours_and_leftover_minutes():
        class MockCompoundContext(BaseVerificationContext):
            @property
            def expires_in_minutes(self) -> int:
                return 125

        ctx = MockCompoundContext(
            recipient_name="Twilight",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert ctx.expires_in_display == "2 hours 5 minutes"


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
                provider_name="UNSUPPORTED_PROVIDER",
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
        context = SpikeRoleContext(
            recipient_name="Twilight",
            club_name="Canterlot Court",
            action_url=HttpUrl("https://canterlot.com.br/club"),
            notifications_url=HttpUrl("https://canterlot.com.br/notifications"),
            role_name=MemberRole.ADMIN,
        )
        dumped = context.model_dump(mode="json")
        assert dumped["role_name"] == "Admin"


def describe_from_domain_constructors():
    def it_constructs_recipient_context():
        user = UserFactory.build()
        ctx = RecipientContext.from_domain(recipient=user)
        assert ctx.recipient_name == user.name

    def it_constructs_club_action_context():
        user = UserFactory.build()
        club = ClubFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = ClubActionContext.from_domain(recipient=user, club=club)
        assert ctx.recipient_name == user.name
        assert ctx.club_name == club.name
        assert str(ctx.action_url) == f"{frontend_url}/clubs/{club.slug}"

    def it_constructs_club_actor_action_context():
        user = UserFactory.build()
        actor = UserFactory.build()
        club = ClubFactory.build()

        ctx = ClubActorActionContext.from_domain(recipient=user, actor=actor, club=club)
        assert ctx.recipient_name == user.name
        assert ctx.actor_name == actor.name
        assert ctx.club_name == club.name

    def it_constructs_auth_provider_context():
        user = UserFactory.build()

        ctx = AuthProviderContext.from_domain(recipient=user, provider_name=AuthProviderName.GOOGLE)
        assert ctx.recipient_name == user.name
        assert ctx.provider_name == "Google"

    def it_constructs_invite_external_context():
        actor = UserFactory.build()
        club = ClubFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = InviteExternalContext.from_domain(inviter=actor, club=club, invite="token-123")
        assert ctx.inviter_name == actor.name
        assert ctx.club_name == club.name
        assert str(ctx.action_url) == f"{frontend_url}/invites/token-123/preview"

    def it_constructs_invite_internal_context():
        user = UserFactory.build()
        actor = UserFactory.build()
        club = ClubFactory.build()

        ctx = InviteInternalContext.from_domain(recipient=user, inviter=actor, club=club, invite="token-123")
        assert ctx.recipient_name == user.name
        assert ctx.inviter_name == actor.name
        assert ctx.club_name == club.name

    def it_constructs_spike_base_context():
        user = UserFactory.build()
        club = ClubFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = SpikeBaseContext.from_domain(recipient=user, club=club)
        assert ctx.recipient_name == user.name
        assert ctx.club_name == club.name
        assert str(ctx.notifications_url) == f"{frontend_url}/notifications"

    def it_constructs_spike_action_context():
        user = UserFactory.build()
        club = ClubFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = SpikeActionContext.from_domain(recipient=user, club=club, action_path="/vote")
        assert ctx.recipient_name == user.name
        assert str(ctx.action_url) == f"{frontend_url}/vote"

    def it_constructs_spike_book_context():
        user = UserFactory.build()
        club = ClubFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = SpikeBookContext.from_domain(
            recipient=user, club=club, book_title="The Art of War", action_path="/books/1"
        )
        assert ctx.book_title == "The Art of War"
        assert str(ctx.action_url) == f"{frontend_url}/books/1"

    def it_constructs_spike_role_context():
        user = UserFactory.build()
        club = ClubFactory.build()

        ctx = SpikeRoleContext.from_domain(recipient=user, club=club, role_name=MemberRole.ADMIN, is_promotion=True)
        assert ctx.role_name == "Admin"
        assert ctx.is_promotion is True

    def it_constructs_password_changed_context():
        user = UserFactory.build()

        ctx_changed = PasswordChangedContext.from_domain(recipient=user, is_creation=False)
        assert ctx_changed.action == "changed"

        ctx_created = PasswordChangedContext.from_domain(recipient=user, is_creation=True)
        assert ctx_created.action == "created"

    def it_constructs_password_reset_validation_context():
        user = UserFactory.build()
        code = secret_code_adapter.validate_python(SOME_CODE)
        frontend_url = get_settings().frontend_url

        ctx = PasswordResetValidationContext.from_domain(recipient=user, code=code, is_creation=False)
        assert ctx.action == "reset"
        assert ctx.action_capitalized == "Reset"
        assert ctx.button_label == "Reset password"
        assert str(ctx.action_url).startswith(f"{frontend_url}/reset-password?token=")

        ctx_create = PasswordResetValidationContext.from_domain(recipient=user, code=code, is_creation=True)
        assert ctx_create.action == "create"

    def it_constructs_luna_provider_action_context():
        user = UserFactory.build()
        frontend_url = get_settings().frontend_url

        ctx = LunaProviderActionContext.from_domain(recipient=user, provider_name=AuthProviderName.GOOGLE)
        assert ctx.provider_name == "Google"
        assert str(ctx.action_url) == f"{frontend_url}/settings/security"


def describe_category_unsubscribe_url():
    def it_builds_a_category_unsubscribe_url():
        user = UserFactory.build(id=PydanticObjectId("507f1f77bcf86cd799439011"))
        frontend_url = get_settings().backend_url

        url = RecipientContext.with_category_unsubscribe(PydanticObjectId(user.id), EmailCategory.ENGAGEMENT)

        assert str(url).startswith(f"{frontend_url}/v1/unsubscribe?token=")


def describe_from_domain_required_field_guards():
    def it_requires_a_club_for_club_action_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="club is required"):
            ClubActionContext.from_domain(recipient=user)

    def it_requires_an_actor_and_club_for_club_actor_action_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="actor and club are required"):
            ClubActorActionContext.from_domain(recipient=user)

    def it_requires_a_provider_name_for_auth_provider_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="provider_name is required"):
            AuthProviderContext.from_domain(recipient=user)

    def it_requires_inviter_club_and_invite_for_invite_internal_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="inviter, club, and invite are required"):
            InviteInternalContext.from_domain(recipient=user)

    def it_requires_a_code_for_email_verification_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="code is required"):
            EmailVerificationContext.from_domain(recipient=user)

    def it_requires_a_club_for_spike_base_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="club is required"):
            SpikeBaseContext.from_domain(recipient=user)

    def it_requires_a_club_and_action_path_for_spike_action_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="club and action_path are required"):
            SpikeActionContext.from_domain(recipient=user)

    def it_requires_a_club_book_title_and_action_path_for_spike_book_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="club, book_title, and action_path are required"):
            SpikeBookContext.from_domain(recipient=user)

    def it_requires_a_club_and_role_name_for_spike_role_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="club and role_name are required"):
            SpikeRoleContext.from_domain(recipient=user)

    def it_requires_a_code_for_password_reset_validation_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="code is required"):
            PasswordResetValidationContext.from_domain(recipient=user)

    def it_requires_a_provider_name_for_luna_provider_action_context():
        user = UserFactory.build()
        with pytest.raises(ValueError, match="provider_name is required"):
            LunaProviderActionContext.from_domain(recipient=user)


def describe_string_constraints():
    @pytest.mark.parametrize("whitespace_string", ["", "   ", "\n", "\t"])
    def it_rejects_empty_or_whitespace_only_strings_for_required_fields(whitespace_string):
        with pytest.raises(ValidationError):
            BaseVerificationContext(
                recipient_name=whitespace_string,
                code=SOME_CODE,
                action_url=HttpUrl("https://canterlot.com.br/verify"),
            )

    def it_strips_leading_and_trailing_whitespace_from_valid_strings():
        context = BaseVerificationContext(
            recipient_name="  Twilight Sparkle  ",
            code=SOME_CODE,
            action_url=HttpUrl("https://canterlot.com.br/verify"),
        )
        assert context.recipient_name == "Twilight Sparkle"


def describe_url_security_constraints():
    @pytest.mark.parametrize(
        "unsecure_url",
        [
            "ftp://canterlot.com.br/files",
        ],
    )
    def it_rejects_non_http_protocols(unsecure_url):
        with pytest.raises(ValidationError):
            BaseVerificationContext(
                recipient_name="Twilight",
                code=SOME_CODE,
                action_url=HttpUrl("https://canterlot.com.br/verify"),
                unsubscribe_url=unsecure_url,  # type: ignore
            )
