from datetime import UTC, datetime
from unittest.mock import AsyncMock

from beanie import PydanticObjectId

from canterlot.constants import EXTERNAL_SUPPRESSION_TEMPLATE
from canterlot.emails.core.definitions import EmailTemplate
from canterlot.emails.core.policy import EmailPolicyEngine
from canterlot.factories import EmailPreferencesFactory, EmailTaskPayloadFactory

CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439033")
NOW = datetime.now(UTC)


def describe_email_policy_engine():
    def describe_is_external_suppressed():
        async def it_returns_true_when_external_suppression_is_active(cache_repo: AsyncMock):
            cache_repo.find.return_value = {"suppressed": "1"}
            email = "twilight@canterlot.dev"

            is_suppressed = await EmailPolicyEngine.is_external_suppressed(email, cache_repo)

            assert is_suppressed is True
            expected_key = EXTERNAL_SUPPRESSION_TEMPLATE.format(email=email)
            cache_repo.find.assert_awaited_once_with(expected_key)

        async def it_returns_false_when_external_suppression_is_absent_or_inactive(cache_repo: AsyncMock):
            email = "twilight@canterlot.dev"

            is_suppressed = await EmailPolicyEngine.is_external_suppressed(email, cache_repo)

            assert is_suppressed is False

    def describe_check_external_suppressions():
        async def it_returns_empty_set_if_emails_list_is_empty(cache_repo: AsyncMock):
            result = await EmailPolicyEngine.check_external_suppressions([], cache_repo)
            assert result == set()
            cache_repo.find_many.assert_not_called()

        async def it_filters_and_returns_only_suppressed_emails(cache_repo: AsyncMock):
            emails = ["twilight@canterlot.dev", "spike@canterlot.dev", "celestia@canterlot.dev"]
            cache_repo.find_many.return_value = [
                {"suppressed": "1"},
                None,
                {"suppressed": "0"},
            ]

            suppressed_set = await EmailPolicyEngine.check_external_suppressions(emails, cache_repo)

            assert suppressed_set == {"twilight@canterlot.dev"}
            expected_keys = [EXTERNAL_SUPPRESSION_TEMPLATE.format(email=e) for e in emails]
            cache_repo.find_many.assert_awaited_once_with(expected_keys)

    def describe_is_delivery_allowed():
        def it_allows_delivery_when_all_gates_pass(engagement_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=engagement_template, club_id=CLUB_ID)
            prefs = EmailPreferencesFactory.build()

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is True

        def it_drops_task_if_category_is_systematically_suppressed(engagement_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=engagement_template, club_id=CLUB_ID)
            prefs = EmailPreferencesFactory.build(
                categories_system_suppressed={engagement_template.category.value: NOW}
            )

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is False

        def it_drops_task_if_user_explicitly_opted_out_of_category(engagement_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=engagement_template, club_id=CLUB_ID)
            prefs = EmailPreferencesFactory.build(categories_opt_out={engagement_template.category.value: NOW})

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is False

        def it_drops_engagement_task_if_user_opted_out_of_specific_club(engagement_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=engagement_template, club_id=CLUB_ID)
            prefs = EmailPreferencesFactory.build(clubs_opt_out={CLUB_ID: NOW})

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is False

        def it_drops_non_transactional_task_for_unverified_emails(engagement_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=engagement_template, club_id=CLUB_ID)
            prefs = EmailPreferencesFactory.build(verified_at=None)

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is False

        def it_allows_transactional_task_even_if_email_is_unverified(transactional_template: EmailTemplate):
            task = EmailTaskPayloadFactory.build(template=transactional_template)
            prefs = EmailPreferencesFactory.build(verified_at=None)

            assert EmailPolicyEngine.is_delivery_allowed(task, prefs) is True
