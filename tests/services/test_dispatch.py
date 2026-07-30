from unittest.mock import AsyncMock, patch

import pytest

from canterlot.emails import EmailTaskPayload
from canterlot.models.user import EmailPreferencesSchema
from canterlot.services.dispatch import EmailDispatchService
from tools.factories import BatchEmailDispatchItemFactory, EmailTaskPayloadFactory


def _create_task(to_email: str = "user@example.com") -> EmailTaskPayload:
    return EmailTaskPayloadFactory.build(to=to_email)


@pytest.fixture
def dispatch_service(email_task_queue: AsyncMock, cache_repo: AsyncMock) -> EmailDispatchService:
    return EmailDispatchService(saq_queue=email_task_queue, cache_repo=cache_repo)


def describe_email_dispatch_service():
    def describe_dispatch():
        async def it_returns_false_when_externally_suppressed(
            dispatch_service: EmailDispatchService,
            cache_repo: AsyncMock,
            email_task_queue: AsyncMock,
        ):
            task = _create_task("suppressed@example.com")
            with patch(
                "canterlot.services.dispatch.EmailPolicyEngine.is_external_suppressed",
                new=AsyncMock(return_value=True),
            ) as mock_suppressed:
                result = await dispatch_service.dispatch(task)

                assert result is False
                mock_suppressed.assert_awaited_once_with("suppressed@example.com", cache_repo)
                email_task_queue.enqueue.assert_not_called()

        async def it_returns_false_when_user_preferences_disallow_delivery(
            dispatch_service: EmailDispatchService,
            email_task_queue: AsyncMock,
        ):
            task = _create_task()
            prefs = EmailPreferencesSchema()
            with (
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.is_external_suppressed",
                    new=AsyncMock(return_value=False),
                ),
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.is_delivery_allowed",
                    return_value=False,
                ) as mock_allowed,
            ):
                result = await dispatch_service.dispatch(task, prefs=prefs)

                assert result is False
                mock_allowed.assert_called_once_with(task, prefs)
                email_task_queue.enqueue.assert_not_called()

        async def it_enqueues_task_and_returns_true_when_checks_pass(
            dispatch_service: EmailDispatchService,
            email_task_queue: AsyncMock,
        ):
            task = _create_task("user@example.com")
            prefs = EmailPreferencesSchema()
            with (
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.is_external_suppressed",
                    new=AsyncMock(return_value=False),
                ),
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.is_delivery_allowed",
                    return_value=True,
                ),
            ):
                result = await dispatch_service.dispatch(task, prefs=prefs)

                assert result is True
                email_task_queue.enqueue.assert_awaited_once_with(
                    "send_email_task",
                    payload_str=task.model_dump_json(),
                    meta={"priority": task.template.priority.value},
                )

    def describe_dispatch_batch():
        async def it_returns_zero_when_items_sequence_is_empty(dispatch_service: EmailDispatchService):
            result = await dispatch_service.dispatch_batch([])
            assert result == 0

        async def it_skips_suppressed_and_disallowed_emails_and_returns_enqueued_count(
            dispatch_service: EmailDispatchService,
            cache_repo: AsyncMock,
            email_task_queue: AsyncMock,
        ):
            task1 = _create_task("suppressed@example.com")
            task2 = _create_task("disallowed@example.com")
            task3 = _create_task("allowed@example.com")
            prefs2 = EmailPreferencesSchema()

            items = [
                BatchEmailDispatchItemFactory.build(task=task1),
                BatchEmailDispatchItemFactory.build(task=task2, prefs=prefs2),
                BatchEmailDispatchItemFactory.build(task=task3),
            ]

            def fake_is_delivery_allowed(task: EmailTaskPayload, _prefs: EmailPreferencesSchema):
                return task.to != "disallowed@example.com"

            with (
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.check_external_suppressions",
                    new=AsyncMock(return_value={"suppressed@example.com"}),
                ) as mock_check_suppressions,
                patch(
                    "canterlot.services.dispatch.EmailPolicyEngine.is_delivery_allowed",
                    side_effect=fake_is_delivery_allowed,
                ),
            ):
                enqueued_count = await dispatch_service.dispatch_batch(items)

                assert enqueued_count == 1
                mock_check_suppressions.assert_awaited_once()
                actual_emails = mock_check_suppressions.call_args[0][0]
                assert set(actual_emails) == {"suppressed@example.com", "disallowed@example.com", "allowed@example.com"}
                assert mock_check_suppressions.call_args[0][1] == cache_repo

                email_task_queue.enqueue.assert_awaited_once_with(
                    "send_email_task",
                    payload_str=task3.model_dump_json(),
                    meta={"priority": task3.template.priority.value},
                )
