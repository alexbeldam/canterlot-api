from typing import TYPE_CHECKING, Any, Self

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, HttpUrl, computed_field

from canterlot.config.settings import get_settings
from canterlot.emails.core.enums import EmailCategory
from canterlot.types import (
    NonEmptyStr,
    SecretVerificationCode,
    TitleCaseAuthProviderName,
    TitleCaseMemberRole,
    VerificationCodeStr,
    VerificationScope,
)
from canterlot.utils.security import (
    encode_action_link_token,
    encode_category_unsubscribe_token,
    encode_club_unsubscribe_token,
)

if TYPE_CHECKING:
    from canterlot.models import ClubModel, UserModel

# ==========================================
# --- BASE CONTEXT CONTRACTS ---
# ==========================================


class BaseEmailContext(BaseModel):
    unsubscribe_url: HttpUrl | None = None

    @classmethod
    def with_club_unsubscribe(cls, user_id: PydanticObjectId, club_id: PydanticObjectId) -> HttpUrl:
        api_url = get_settings().backend_url
        token = encode_club_unsubscribe_token(user_id, club_id)
        return HttpUrl(f"{api_url}/v1/unsubscribe?token={token}")

    @classmethod
    def with_category_unsubscribe(cls, user_id: PydanticObjectId, category: EmailCategory) -> HttpUrl:
        api_url = get_settings().backend_url
        token = encode_category_unsubscribe_token(user_id, category)
        return HttpUrl(f"{api_url}/v1/unsubscribe?token={token}")


class RecipientContext(BaseEmailContext):
    """Strictly requires a known recipient greeting."""

    recipient_name: NonEmptyStr

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        **kwargs: Any,
    ) -> Self:
        return cls(
            recipient_name=recipient.name,
            unsubscribe_url=kwargs.get("unsubscribe_url"),
        )


# ==========================================
# --- SHARED REUSABLE STRUCTURES ---
# ==========================================


class BaseVerificationContext(RecipientContext):
    """Required data for verification links (Email Confirmations & Password Resets)."""

    code: VerificationCodeStr
    action_url: HttpUrl

    @property
    def expires_in_minutes(self) -> int:
        raise NotImplementedError("Subclasses must define expires_in_minutes.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expires_in_display(self) -> str:
        if self.expires_in_minutes < 60:  # noqa: PLR2004
            return f"{self.expires_in_minutes} minutes"

        hours = self.expires_in_minutes // 60
        minutes = self.expires_in_minutes % 60

        hour_str = f"{hours} hour" if hours == 1 else f"{hours} hours"

        if minutes == 0:
            return hour_str

        return f"{hour_str} {minutes} minutes"


class ClubActionContext(RecipientContext):
    """Required data for interacting directly with a specific club."""

    club_name: NonEmptyStr
    action_url: HttpUrl

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        club: "ClubModel | None" = None,
        **kwargs: Any,
    ) -> Self:
        if club is None:
            raise ValueError("club is required for ClubActionContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", True)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            club_name=club.name,
            action_url=HttpUrl(f"{root_url}/clubs/{club.slug}"),
            unsubscribe_url=unsub_url,
        )


class ClubActorActionContext(ClubActionContext):
    """Required data for club actions triggered by an explicit actor (e.g. transfers)."""

    actor_name: NonEmptyStr

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        actor: "UserModel | None" = None,
        club: "ClubModel | None" = None,
        **kwargs: Any,
    ) -> Self:
        if actor is None or club is None:
            raise ValueError("actor and club are required for ClubActorActionContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", False)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            actor_name=actor.name,
            club_name=club.name,
            action_url=HttpUrl(f"{root_url}/clubs/{club.slug}"),
            unsubscribe_url=unsub_url,
        )


class AuthProviderContext(RecipientContext):
    """Context for simple provider actions (e.g., disconnecting an OAuth method)."""

    provider_name: TitleCaseAuthProviderName

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        provider_name: TitleCaseAuthProviderName | None = None,
        **kwargs: Any,
    ) -> Self:
        if provider_name is None:
            raise ValueError("provider_name is required for AuthProviderContext")

        return cls(
            recipient_name=recipient.name,
            provider_name=provider_name,
            unsubscribe_url=kwargs.get("unsubscribe_url"),
        )


# ==========================================
# --- CELESTIA CONTEXTS ---
# ==========================================


class InviteExternalContext(BaseEmailContext):
    """Requires no recipient name as they are external, but needs tracking info."""

    inviter_name: NonEmptyStr
    club_name: NonEmptyStr
    action_url: HttpUrl

    @classmethod
    def from_domain(
        cls,
        *,
        inviter: "UserModel",
        club: "ClubModel",
        invite: str,
    ) -> Self:
        root_url = get_settings().frontend_url

        return cls(
            inviter_name=inviter.name,
            club_name=club.name,
            action_url=HttpUrl(f"{root_url}/invites/{invite}/preview"),
        )


class InviteInternalContext(ClubActionContext):
    """An internal invitation from a specific member."""

    inviter_name: NonEmptyStr

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        inviter: "UserModel | None" = None,
        club: "ClubModel | None" = None,
        invite: str | None = None,
        **_kwargs: Any,
    ) -> Self:
        if inviter is None or club is None or invite is None:
            raise ValueError("inviter, club, and invite are required for InviteInternalContext")

        root_url = get_settings().frontend_url

        return cls(
            recipient_name=recipient.name,
            inviter_name=inviter.name,
            club_name=club.name,
            action_url=HttpUrl(f"{root_url}/invites/{invite}/preview"),
            unsubscribe_url=None,
        )


class EmailVerificationContext(BaseVerificationContext):
    """Context wrapper for email change confirmations."""

    @property
    def expires_in_minutes(self) -> int:
        return VerificationScope.EMAIL.ttl_minutes

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        code: SecretVerificationCode | None = None,
        **_kwargs: Any,
    ) -> Self:
        if code is None:
            raise ValueError("code is required for EmailVerificationContext")

        root_url = get_settings().frontend_url
        token = encode_action_link_token(PydanticObjectId(recipient.id), code)

        return cls(
            recipient_name=recipient.name,
            code=code.get_secret_value(),
            action_url=HttpUrl(f"{root_url}/verify-email?token={token}"),
            unsubscribe_url=None,
        )


# ==========================================
# --- SPIKE CONTEXTS ---
# ==========================================


class SpikeBaseContext(RecipientContext):
    """Strict context for Spike notifications without an actionable link (e.g. Removed, Dissolved)."""

    club_name: NonEmptyStr
    notifications_url: HttpUrl

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        club: "ClubModel | None" = None,
        **kwargs: Any,
    ) -> Self:
        if club is None:
            raise ValueError("club is required for SpikeBaseContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", True)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            club_name=club.name,
            notifications_url=HttpUrl(f"{root_url}/notifications"),
            unsubscribe_url=unsub_url,
        )


class SpikeActionContext(SpikeBaseContext):
    """Strict context for Spike notifications that include an interaction button (e.g. Voting Open)."""

    action_url: HttpUrl

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        club: "ClubModel | None" = None,
        action_path: str | None = None,
        **kwargs: Any,
    ) -> Self:
        if club is None or action_path is None:
            raise ValueError("club and action_path are required for SpikeActionContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", True)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            club_name=club.name,
            notifications_url=HttpUrl(f"{root_url}/notifications"),
            action_url=HttpUrl(f"{root_url}{action_path}"),
            unsubscribe_url=unsub_url,
        )


class SpikeBookContext(SpikeActionContext):
    """Required details for book deadlines or selections."""

    book_title: NonEmptyStr

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        club: "ClubModel | None" = None,
        book_title: NonEmptyStr | None = None,
        action_path: str | None = None,
        **kwargs: Any,
    ) -> Self:
        if club is None or book_title is None or action_path is None:
            raise ValueError("club, book_title, and action_path are required for SpikeBookContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", True)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            club_name=club.name,
            book_title=book_title,
            notifications_url=HttpUrl(f"{root_url}/notifications"),
            action_url=HttpUrl(f"{root_url}{action_path}"),
            unsubscribe_url=unsub_url,
        )


class SpikeRoleContext(SpikeActionContext):
    """Required details for a membership role update notification."""

    role_name: TitleCaseMemberRole
    is_promotion: bool = True

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        club: "ClubModel | None" = None,
        role_name: TitleCaseMemberRole | None = None,
        is_promotion: bool = True,
        **kwargs: Any,
    ) -> Self:
        if club is None or role_name is None:
            raise ValueError("club and role_name are required for SpikeRoleContext")

        root_url = get_settings().frontend_url
        include_unsubscribe = kwargs.get("include_unsubscribe", True)

        unsub_url = (
            cls.with_club_unsubscribe(
                PydanticObjectId(recipient.id),
                PydanticObjectId(club.id),
            )
            if include_unsubscribe
            else kwargs.get("unsubscribe_url")
        )

        return cls(
            recipient_name=recipient.name,
            club_name=club.name,
            role_name=role_name,
            is_promotion=is_promotion,
            notifications_url=HttpUrl(f"{root_url}/notifications"),
            action_url=HttpUrl(f"{root_url}/clubs/{club.slug}/members"),
            unsubscribe_url=unsub_url,
        )


# ==========================================
# --- LUNA CONTEXTS ---
# ==========================================


class PasswordChangedContext(RecipientContext):
    """Context for password creation, change, or reset notifications."""

    is_creation: bool = Field(
        default=False,
        description="True if the user set a password for the first time; False if updated or reset.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def action(self) -> str:
        """Returns the verb describing the operation."""
        return "created" if self.is_creation else "changed"

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        is_creation: bool = False,
        **kwargs: Any,
    ) -> Self:
        return cls(
            recipient_name=recipient.name,
            is_creation=is_creation,
            unsubscribe_url=kwargs.get("unsubscribe_url"),
        )


class PasswordResetValidationContext(BaseVerificationContext):
    """Context wrapper for password recovery or initial password setup."""

    is_creation: bool = Field(
        default=False,
        description="True if the user is setting up a password for the first time; False if resetting an existing one.",
    )

    @property
    def expires_in_minutes(self) -> int:
        return VerificationScope.PASSWORD_RESET.ttl_minutes

    @computed_field  # type: ignore[prop-decorator]
    @property
    def action(self) -> str:
        """Returns the verb describing the operation."""
        return "create" if self.is_creation else "reset"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def action_capitalized(self) -> str:
        """Capitalized verb for subject line formatting."""
        return self.action.capitalize()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def button_label(self) -> str:
        """Full button label for the template call-to-action."""
        return f"{self.action_capitalized} password"

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        code: SecretVerificationCode | None = None,
        is_creation: bool = False,
        **_kwargs: Any,
    ) -> Self:
        if code is None:
            raise ValueError("code is required for PasswordResetValidationContext")

        root_url = get_settings().frontend_url
        token = encode_action_link_token(PydanticObjectId(recipient.id), code)

        return cls(
            recipient_name=recipient.name,
            code=code.get_secret_value(),
            is_creation=is_creation,
            action_url=HttpUrl(f"{root_url}/reset-password?token={token}"),
            unsubscribe_url=None,
        )


class LunaProviderActionContext(AuthProviderContext):
    """Context for complex provider actions containing a fallback URL (e.g., Linked, Locked Out)."""

    action_url: HttpUrl

    @classmethod
    def from_domain(
        cls,
        *,
        recipient: "UserModel",
        provider_name: TitleCaseAuthProviderName | None = None,
        **kwargs: Any,
    ) -> Self:
        if provider_name is None:
            raise ValueError("provider_name is required for LunaProviderActionContext")

        root_url = get_settings().frontend_url

        return cls(
            recipient_name=recipient.name,
            provider_name=provider_name,
            action_url=HttpUrl(f"{root_url}/settings/security"),
            unsubscribe_url=kwargs.get("unsubscribe_url"),
        )
