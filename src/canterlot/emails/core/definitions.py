from enum import Enum

from pydantic import BaseModel

from canterlot.emails.core import schemas


class SubBrand(Enum):
    CELESTIA = (1, False)
    SPIKE = (2, True)
    LUNA = (3, False)

    def __init__(self, index: int, includes_preferences: bool = False):
        self.index = index
        self.folder = self.name.lower()
        self.sender = f"{self.name.title()} · Canterlot <{self.name.lower()}@noreply.canterlot.com.br>"
        self.includes_preferences = includes_preferences


class EmailTemplate(Enum):
    # --- CELESTIA TEMPLATES ---
    CELESTIA_VERIFY_EMAIL = (
        SubBrand.CELESTIA,
        "verify-email",
        "Confirm your email on Canterlot",
        schemas.VerificationContext,
    )
    CELESTIA_VERIFY_EMAIL_CHANGED = (
        SubBrand.CELESTIA,
        "verify-email-changed",
        "Confirm your new email on Canterlot",
        schemas.VerificationContext,
    )
    CELESTIA_INVITE_EXTERNAL = (
        SubBrand.CELESTIA,
        "invite-external",
        "{inviter_name} invited you to the {club_name}",
        schemas.InviteExternalContext,
    )
    CELESTIA_INVITE_INTERNAL = (
        SubBrand.CELESTIA,
        "invite-internal",
        "{inviter_name} invited you to the {club_name}",
        schemas.InviteInternalContext,
    )
    CELESTIA_APPROVED = (
        SubBrand.CELESTIA,
        "approved",
        "You were approved to the {club_name}!",
        schemas.ClubActionContext,
    )
    CELESTIA_OWNERSHIP_RECEIVED = (
        SubBrand.CELESTIA,
        "ownership-received",
        "You are now owner of the {club_name}",
        schemas.ClubActorActionContext,
    )

    # --- SPIKE TEMPLATES ---
    SPIKE_BOOK_DECIDED = (
        SubBrand.SPIKE,
        "book-decided",
        "{club_name}: time to start reading {book_title}",
        schemas.SpikeBookContext,
    )
    SPIKE_VOTING_OPEN = (
        SubBrand.SPIKE,
        "voting-open",
        "{club_name}: vote on the next book",
        schemas.SpikeActionContext,
    )
    SPIKE_REMINDER_T1 = (
        SubBrand.SPIKE,
        "reminder-t1",
        "{club_name}: 1 day left for {book_title} deadline",
        schemas.SpikeBookContext,
    )
    SPIKE_REMINDER_T0 = (
        SubBrand.SPIKE,
        "reminder-t0",
        "{club_name}: {book_title} deadline is today",
        schemas.SpikeBookContext,
    )
    SPIKE_ROLE_CHANGED = (
        SubBrand.SPIKE,
        "role-changed",
        "Your role in {club_name} changed to {role_name}",
        schemas.SpikeRoleContext,
    )
    SPIKE_REMOVED = (SubBrand.SPIKE, "removed", "You were removed from the {club_name}", schemas.SpikeBaseContext)
    SPIKE_CLUB_DISSOLVED = (
        SubBrand.SPIKE,
        "club-dissolved",
        "The {club_name} was disbanded",
        schemas.SpikeActionContext,
    )

    # --- LUNA TEMPLATES ---
    LUNA_PASSWORD_RESET = (
        SubBrand.LUNA,
        "password-reset",
        "Reset your password on Canterlot",
        schemas.VerificationContext,
    )
    LUNA_LOCKED_OUT = (
        SubBrand.LUNA,
        "locked-out",
        "You have no login methods left",
        schemas.LunaProviderActionContext,
    )
    LUNA_PASSWORD_CHANGED = (
        SubBrand.LUNA,
        "password-changed",
        "Your password was changed",
        schemas.RecipientContext,
    )
    LUNA_PROVIDER_LINKED = (
        SubBrand.LUNA,
        "provider-linked",
        "You linked {provider_name} to your account",
        schemas.LunaProviderActionContext,
    )
    LUNA_PROVIDER_DISCONNECTED = (
        SubBrand.LUNA,
        "provider-disconnected",
        "You unlinked {provider_name} from your account",
        schemas.LunaProviderContext,
    )
    LUNA_EMAIL_CHANGED = (
        SubBrand.LUNA,
        "email-changed",
        "Your account email was changed",
        schemas.RecipientContext,
    )
    LUNA_OWNERSHIP_TRANSFERRED = (
        SubBrand.LUNA,
        "ownership-transferred",
        "You transferred ownership of {club_name}",
        schemas.ClubActorActionContext,
    )
    LUNA_OWNERSHIP_RECLAIMED = (
        SubBrand.LUNA,
        "ownership-reclaimed",
        "Your transfer of {club_name} was reverted",
        schemas.LunaOwnershipReclaimedContext,
    )

    def __init__(self, brand: SubBrand, slug: str, subject_template: str, context_schema: type[BaseModel]):
        self.brand = brand
        self.slug = slug
        self.subject_template = subject_template
        self.context_schema = context_schema

    @property
    def template_path(self) -> str:
        return f"{self.brand.folder}/{self.slug}.html.j2"
