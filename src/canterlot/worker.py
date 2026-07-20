import asyncio
import time
from datetime import UTC, datetime
from typing import Required

from redis.asyncio import Redis
from saq import Queue, Status, Worker
from saq.queue.redis import RedisQueue
from saq.types import Context

from canterlot.config import get_settings
from canterlot.config.database import DatabaseManager
from canterlot.constants import DEAD_LETTER_QUEUE_NAME, EMAIL_TASKS_QUEUE_NAME, QUOTA_LOCK_KEY
from canterlot.emails import EmailClient, EmailPriority, EmailTaskPayload, get_email_client, render_email_template
from canterlot.emails.core.policy import EmailPolicyEngine
from canterlot.repositories import CacheRepository
from canterlot.repositories.beanie import BeanieUserRepository
from canterlot.repositories.redis import RedisRepository
from canterlot.services import UserService
from canterlot.utils import get_logger, setup_logging

logger = get_logger(__name__)

ONE_HOUR = 3600
SIX_HOURS = 6 * ONE_HOUR


class CanterlotContext(Context, total=False):
    cache_repo: Required[CacheRepository]
    user_service: Required[UserService]
    email_client: Required[EmailClient]
    dlq_queue: Required[Queue]
    abort_job: bool


async def before_process_hook(ctx: CanterlotContext) -> bool:
    job = ctx.get("job")
    if not job or not job.queue:
        return False

    log = logger.bind(job_id=job.id)

    repo = ctx["cache_repo"]
    user_service = ctx["user_service"]
    priority_val = job.meta.get("priority") if job.meta else None
    kwargs = job.kwargs or {}

    # 1. Evaluate Global Upstream Quota Lock Gate
    quota_depleted = await repo.find(QUOTA_LOCK_KEY)
    if quota_depleted and priority_val != EmailPriority.HIGH.value:
        log.warning("Global quota lock active. Postponing non-high priority job.")
        await job.queue.enqueue(job.function, scheduled=time.time() + 15, meta=job.meta, **kwargs)
        ctx["abort_job"] = True
        return False

    # 2. Parse Payload and Evaluate Recipient Operational Failure State
    payload_str = kwargs.get("payload_str")
    try:
        if not payload_str or not isinstance(payload_str, str):
            raise ValueError("Job missing payload string argument.")
        payload = EmailTaskPayload.model_validate_json(payload_str)
    except Exception as parse_exc:
        log.critical("Failed parsing task metadata during hook evaluation.", exc_info=parse_exc)
        return False

    log = log.bind(email=payload.to, priority=priority_val)

    # Stale validation check for low-priority tasks
    task_age = (datetime.now(UTC) - payload.created_at).total_seconds()
    if priority_val == EmailPriority.LOW.value and task_age > SIX_HOURS:
        log.bind(age=task_age).debug("Dropping stale low-priority task entirely.")
        return False

    # Evaluate transient delivery failure flags set by webhook pipeline
    prefs = await user_service.get_email_preferences(payload.to)
    if prefs.delivery_failed and priority_val != EmailPriority.HIGH.value:
        log.info("Recipient operational lock active. Postponing job execution.")
        await job.queue.enqueue(job.function, scheduled=time.time() + 300, meta=job.meta, **kwargs)
        ctx["abort_job"] = True
        return False

    # 3. Tracked Domain Rate-Limiting Pacing
    settings = get_settings()
    pacing_interval = (1.0 / settings.email_rate_limit) if settings.email_rate_limit > 0 else 0.0
    if pacing_interval > 0:
        log.bind(pacing_interval=pacing_interval).debug("Applying rate-limiting pacing delay.")
        await asyncio.sleep(pacing_interval)

    return True


async def after_process_hook(ctx: CanterlotContext) -> None:
    """
    Lifecycle hook running post-execution. Intercepts terminal errors for the DLQ.
    """
    job = ctx.get("job")
    if not job:
        return

    if job.status == Status.FAILED:
        kwargs = job.kwargs or {}
        max_retries = kwargs.get("retries", 3)

        if job.attempts >= max_retries:
            logger.bind(job_id=job.id, function=job.function, error=str(job.error)).error(
                "Job exhausted all active retry attempts. Offloading to Dead Letter Queue."
            )

            dlq_queue = ctx["dlq_queue"]

            meta_payload = {
                "original_job_id": job.id,
                "failed_at": time.time(),
                "traceback": job.error,
            }
            if job.meta:
                meta_payload["priority"] = job.meta.get("priority")

            await dlq_queue.enqueue(
                job.function,
                payload_str=kwargs.get("payload_str"),
                meta=meta_payload,
            )


async def send_email_task(ctx: CanterlotContext, payload_str: str) -> None:
    if ctx.get("abort_job"):
        return

    job = ctx.get("job")
    job_id = job.id if job else "unknown"

    repo = ctx["cache_repo"]
    user_service = ctx["user_service"]
    email_client = ctx["email_client"]

    task = EmailTaskPayload.model_validate_json(payload_str)
    log = logger.bind(job_id=job_id, email=task.to, template_name=task.template.name)

    # 1. Evaluate Infrastructure Suppression Gate Checklist
    if await EmailPolicyEngine.is_external_suppressed(task.to, repo):
        log.debug("Email delivery skipped: external suppression gate active.")
        return

    # 2. Final Domain Policy Validation Check
    prefs = await user_service.get_email_preferences(task.to)
    if not EmailPolicyEngine.is_delivery_allowed(task, prefs):
        log.debug("Email delivery skipped: failed final domain policy validation check.")
        return

    # 3. Compile and Deliver Upstream
    try:
        log.debug("Compiling and rendering email template.")
        rendered = render_email_template(task.template, task.context)
        message = rendered.to_message(to=task.to)

        log.debug("Attempting upstream delivery.")
        result = await email_client.send(message)

        if not result.success and result.disabled:
            log.warning("Upstream reported quota exhaustion. Triggering global circuit breaker.")
            await repo.save(QUOTA_LOCK_KEY, {"status": "active"}, expire_seconds=ONE_HOUR)
            raise RuntimeError("Upstream provider rate limit reached.")

        log.info("Email successfully sent upstream.")

    except Exception as run_exc:
        log.error("Failed handling execution template routing.", exc_info=run_exc)
        raise run_exc


async def run_worker() -> None:
    settings = get_settings()
    setup_logging(settings.environment)

    email_client = get_email_client()

    async with DatabaseManager():
        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=15.0,
            socket_keepalive=True,
            health_check_interval=10,
        )

        cache_repo = RedisRepository(redis_client)
        user_repo = BeanieUserRepository()
        user_service = UserService(user_repo=user_repo, cache_repo=cache_repo)
        saq_queue = RedisQueue(redis_client, name=EMAIL_TASKS_QUEUE_NAME)
        dlq_queue = RedisQueue(redis_client, name=DEAD_LETTER_QUEUE_NAME)

        async def startup_hook(ctx: CanterlotContext) -> None:
            ctx["cache_repo"] = cache_repo
            ctx["user_service"] = user_service
            ctx["email_client"] = email_client
            ctx["dlq_queue"] = dlq_queue

        worker = Worker(
            queue=saq_queue,
            functions=[send_email_task],
            startup=startup_hook,
            before_process=before_process_hook,
            after_process=after_process_hook,
            concurrency=4,
        )

        try:
            logger.info("Canterlot SAQ worker engine live with DLQ routing listening.")
            await worker.start()
        finally:
            await redis_client.aclose()


def main() -> None:
    asyncio.run(run_worker())
