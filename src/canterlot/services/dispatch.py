from saq import Queue

from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.policy import EmailPolicyEngine
from canterlot.repositories import CacheRepository
from canterlot.services import UserService


class EmailDispatchService:
    def __init__(
        self,
        saq_queue: Queue,
        cache_repo: CacheRepository,
        user_service: UserService,
    ):
        self.queue = saq_queue
        self.cache_repo = cache_repo
        self.user_service = user_service

    async def dispatch(self, task: EmailTaskPayload) -> bool:
        # 1. External Infrastructure Suppression Gate Check
        if await EmailPolicyEngine.is_external_suppressed(task.to, self.cache_repo):
            return False

        # 2. Fetch User Context
        prefs = await self.user_service.get_email_preferences(task.to)

        # 3. Delegate evaluation to the pure Domain Policy Engine
        if not EmailPolicyEngine.is_delivery_allowed(task, prefs):
            return False

        # 4. Enqueue to SAQ worker pool. Tag priority in metadata for before_process hooks.
        await self.queue.enqueue(
            "send_email_task",
            payload_str=task.model_dump_json(),
            meta={"priority": task.template.priority.value},
        )
        return True
