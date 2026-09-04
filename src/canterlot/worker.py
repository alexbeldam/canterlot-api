import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Required

from redis.asyncio import Redis
from redis.maint_notifications import MaintNotificationsConfig
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
    email_payload: EmailTaskPayload[Any]


async def _requeue_job(job: Any, delay_seconds: float, kwargs: dict[str, Any]) -> None:
    await job.queue.enqueue(job.function, scheduled=time.time() + delay_seconds, meta=job.meta, **kwargs)


async def _is_quota_lock_active(
    ctx: CanterlotContext, priority_val: object, job: Any, kwargs: dict[str, Any], log: Any
) -> bool:
    repo = ctx["cache_repo"]
    quota_depleted = await repo.find(QUOTA_LOCK_KEY)
    if not quota_depleted or priority_val == EmailPriority.HIGH.value:
        return False

    log.warning("Global quota lock active. Postponing non-high priority job.")
    await _requeue_job(job, 15, kwargs)
    ctx["abort_job"] = True
    return True


def _resolve_email_payload(payload_str: object, log: Any) -> EmailTaskPayload[Any] | None:
    if not payload_str or not isinstance(payload_str, str):
        log.critical("Failed parsing task metadata during hook evaluation.")
        return None

    try:
        return EmailTaskPayload[Any].model_validate_json(payload_str)
    except Exception as parse_exc:
        log.critical("Failed parsing task metadata during hook evaluation.", exc_info=parse_exc)
        return None


def _is_stale_low_priority_task(payload: EmailTaskPayload[Any], priority_val: object, log: Any) -> bool:
    if priority_val != EmailPriority.LOW.value:
        return False

    task_age = (datetime.now(UTC) - payload.created_at).total_seconds()
    if task_age <= SIX_HOURS:
        return False

    log.bind(age=task_age).debug("Dropping stale low-priority task entirely.")
    return True


async def _is_recipient_operationally_locked(
    ctx: CanterlotContext,
    payload: EmailTaskPayload[Any],
    priority_val: object,
    job: Any,
    kwargs: dict[str, Any],
    log: Any,
) -> bool:
    user_service = ctx["user_service"]
    prefs = await user_service.get_email_preferences(payload.to)
    if not prefs.delivery_failed or priority_val == EmailPriority.HIGH.value:
        return False

    log.info("Recipient operational lock active. Postponing job execution.")
    await _requeue_job(job, 300, kwargs)
    ctx["abort_job"] = True
    return True


async def _apply_dispatch_pacing(log: Any) -> None:
    settings = get_settings().email
    pacing_interval = (1.0 / settings.dispatch_max_rps) if settings.dispatch_max_rps > 0 else 0.0
    if pacing_interval <= 0:
        return

    log.bind(pacing_interval=pacing_interval).debug("Applying rate-limiting pacing delay.")
    await asyncio.sleep(pacing_interval)


async def before_process_hook(ctx: CanterlotContext) -> bool:
    job = ctx.get("job")
    if not job or not job.queue:
        return False

    log = logger.bind(job_id=job.id)
    priority_val = job.meta.get("priority") if job.meta else None
    kwargs = job.kwargs or {}

    if await _is_quota_lock_active(ctx, priority_val, job, kwargs, log):
        return False

    payload = _resolve_email_payload(kwargs.get("payload_str"), log)
    if payload is None:
        return False
    ctx["email_payload"] = payload

    log = log.bind(email=payload.to, priority=priority_val)

    if _is_stale_low_priority_task(payload, priority_val, log):
        return False

    if await _is_recipient_operationally_locked(ctx, payload, priority_val, job, kwargs, log):
        return False

    await _apply_dispatch_pacing(log)
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

    task = ctx.get("email_payload")
    if not task:
        logger.debug("Job context missing email_payload. Falling back to explicit JSON validation.")
        try:
            task = EmailTaskPayload.model_validate_json(payload_str)
        except Exception as parse_exc:
            logger.bind(job_id=job_id).critical("Failed to parse fallback payload string.", exc_info=parse_exc)
            return

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


def build_worker(redis_client: Redis) -> Worker:
    email_client = get_email_client()
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

    return Worker(
        queue=saq_queue,
        functions=[send_email_task],
        startup=startup_hook,
        before_process=before_process_hook,
        after_process=after_process_hook,
        concurrency=4,
    )


async def run_worker() -> None:
    settings = get_settings()
    setup_logging(settings.environment)

    async with DatabaseManager():
        redis_client = Redis.from_url(
            settings.db.redis_url.get_secret_value(),
            socket_timeout=15.0,
            socket_keepalive=True,
            health_check_interval=10,
            maint_notifications_config=MaintNotificationsConfig(enabled=False),
        )

        worker = build_worker(redis_client)

        try:
            logger.info("Canterlot SAQ worker engine live with DLQ routing listening.")
            await worker.start()
        finally:
            await redis_client.aclose()


def main() -> None:
    asyncio.run(run_worker())
