from pydantic import BaseModel, HttpUrl

from canterlot.types import HttpsUrl, NonEmptyStr, TitleCaseAuthProviderName, TitleCaseMemberRole, VerificationCodeStr

# ==========================================
# --- BASE CONTEXT CONTRACTS ---
# ==========================================


class BaseEmailContext(BaseModel):
    unsubscribe_url: HttpsUrl = HttpUrl("https://canterlot.com.br/unsubscribe")


class RecipientContext(BaseEmailContext):
    """Strictly requires a known recipient greeting."""

    recipient_name: NonEmptyStr


# ==========================================
# --- SHARED REUSABLE STRUCTURES ---
# ==========================================


class VerificationContext(RecipientContext):
    """Required data for verification links (Email Confirmations & Password Resets)."""

    code: VerificationCodeStr
    action_url: HttpsUrl


class ClubActionContext(RecipientContext):
    """Required data for interacting directly with a specific club."""

    club_name: NonEmptyStr
    action_url: HttpsUrl


class ClubActorActionContext(ClubActionContext):
    """Required data for club actions triggered by an explicit actor (e.g. transfers)."""

    actor_name: NonEmptyStr


# ==========================================
# --- CELESTIA CONTEXTS ---
# ==========================================


class InviteExternalContext(BaseEmailContext):
    """Requires no recipient name as they are external, but needs tracking info."""

    inviter_name: NonEmptyStr
    club_name: NonEmptyStr
    action_url: HttpsUrl


class InviteInternalContext(ClubActionContext):
    """An internal invitation from a specific member."""

    inviter_name: NonEmptyStr


# ==========================================
# --- SPIKE CONTEXTS ---
# ==========================================


class SpikeBaseContext(RecipientContext):
    """Strict context for Spike notifications without an actionable link (e.g. Removed, Dissolved)."""

    club_name: NonEmptyStr
    notifications_url: HttpsUrl


class SpikeActionContext(SpikeBaseContext):
    """Strict context for Spike notifications that include an interaction button (e.g. Voting Open)."""

    action_url: HttpsUrl


class SpikeBookContext(SpikeActionContext):
    """Required details for book deadlines or selections."""

    book_title: NonEmptyStr


class SpikeRoleContext(SpikeActionContext):
    """Required details for a membership role update notification."""

    role_name: TitleCaseMemberRole
    is_promotion: bool = True


# ==========================================
# --- LUNA CONTEXTS ---
# ==========================================


class LunaProviderContext(RecipientContext):
    """Context for simple provider actions (e.g., disconnecting an OAuth method)."""

    provider_name: TitleCaseAuthProviderName


class LunaProviderActionContext(LunaProviderContext):
    """Context for complex provider actions containing a fallback URL (e.g., Linked, Locked Out)."""

    action_url: HttpsUrl


class LunaOwnershipReclaimedContext(ClubActorActionContext):
    """Context specifically mapping out role reclaims."""

    role_name: TitleCaseMemberRole
