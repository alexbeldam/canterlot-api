from typing import TYPE_CHECKING

from canterlot.constants import EXTERNAL_SUPPRESSION_TEMPLATE
from canterlot.emails.core.definitions import EmailCategory, EmailTaskPayload
from canterlot.types import NormalizedEmailStr
from canterlot.utils import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from canterlot.models.user import EmailPreferencesSchema
    from canterlot.repositories import CacheRepository


class EmailPolicyEngine:
    @staticmethod
    async def is_external_suppressed(email: NormalizedEmailStr, cache_repo: "CacheRepository") -> bool:
        external_block = await cache_repo.find(EXTERNAL_SUPPRESSION_TEMPLATE.format(email=email))

        return bool(external_block and external_block.get("suppressed") == "1")

    @staticmethod
    def is_delivery_allowed(task: EmailTaskPayload, preferences: "EmailPreferencesSchema") -> bool:
        log = logger.bind(
            email=task.to,
            category=task.template.category,
            club_id=task.club_id,
        )

        # 1. Permanent System Suppressions Gate (Bounces / Complaints)
        if task.template.category in preferences.categories_system_suppressed:
            log.warning("Dropping task: Category systematically suppressed for recipient.")
            return False

        # 2. Explicit User Configuration Opt-outs Gate
        if task.template.category in preferences.categories_opt_out:
            log.debug("Dropping task: User explicitly opted out of category.")
            return False

        if task.club_id and task.club_id in preferences.clubs_opt_out:
            log.debug("Dropping task: User explicitly opted out of club ID.")
            return False

        # 3. Global Unverified Email Verification Gate
        if preferences.verified_at is None and task.template.category != EmailCategory.TRANSACTIONAL:
            log.debug("Dropping task: Recipient has an unverified email address state.")
            return False

        return True
