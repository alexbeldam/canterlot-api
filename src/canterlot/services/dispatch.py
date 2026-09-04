from collections.abc import Sequence
from dataclasses import dataclass

from saq import Queue

from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.policy import EmailPolicyEngine
from canterlot.models.user import EmailPreferencesSchema
from canterlot.repositories import CacheRepository


@dataclass(frozen=True, slots=True)
class BatchEmailDispatchItem:
    task: EmailTaskPayload
    prefs: EmailPreferencesSchema | None = None


class EmailDispatchService:
    def __init__(self, saq_queue: Queue, cache_repo: CacheRepository):
        self.__queue = saq_queue
        self.__cache_repo = cache_repo

    async def dispatch(self, task: EmailTaskPayload, prefs: EmailPreferencesSchema | None = None) -> bool:
        # 1. External Infrastructure Suppression Gate Check
        if await EmailPolicyEngine.is_external_suppressed(task.to, self.__cache_repo):
            return False

        # 3. Delegate evaluation to the pure Domain Policy Engine
        if prefs and not EmailPolicyEngine.is_delivery_allowed(task, prefs):
            return False

        # 4. Enqueue to SAQ worker pool. Tag priority in metadata for before_process hooks.
        await self.__queue.enqueue(
            "send_email_task",
            payload_str=task.model_dump_json(),
            meta={"priority": task.template.priority.value},
        )
        return True

    async def dispatch_batch(
        self,
        items: Sequence[BatchEmailDispatchItem],
    ) -> int:
        """Dispatches multiple email tasks in batch with a single bulk cache suppression lookup.

        Returns the total count of successfully enqueued emails.
        """
        if not items:
            return 0

        unique_emails = list({item.task.to for item in items})
        suppressed_emails = await EmailPolicyEngine.check_external_suppressions(
            unique_emails,
            self.__cache_repo,
        )

        enqueued_count = 0

        for item in items:
            # 1. External Infrastructure Suppression Gate Check
            if item.task.to in suppressed_emails:
                continue

            # 2. Pure Domain Policy Engine Gate Check
            if item.prefs and not EmailPolicyEngine.is_delivery_allowed(item.task, item.prefs):
                continue

            # 3. Enqueue to SAQ worker pool
            await self.__queue.enqueue(
                "send_email_task",
                payload_str=item.task.model_dump_json(),
                meta={"priority": item.task.template.priority.value},
            )
            enqueued_count += 1

        return enqueued_count
