from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from saq import Status

from canterlot.constants import QUOTA_LOCK_KEY
from canterlot.emails import EmailClient, EmailPriority, EmailSendResult
from canterlot.worker import (
    CanterlotContext,
    after_process_hook,
    before_process_hook,
    main,
    run_worker,
    send_email_task,
)
from tools.factories import EmailTaskPayloadFactory


@pytest.fixture
def email_client():
    client = MagicMock(spec=EmailClient)
    result = MagicMock(spec=EmailSendResult)
    result.success = True
    result.disabled = False
    client.send = AsyncMock(return_value=result)
    return client


@pytest.fixture
def base_payload():
    return EmailTaskPayloadFactory.build(to="twilight@canterlot.dev")


@pytest.fixture
def ctx(cache_repo, user_service, email_client, email_task_queue) -> CanterlotContext:
    cache_repo.find = AsyncMock(return_value=None)
    cache_repo.save = AsyncMock()

    prefs = MagicMock()
    prefs.delivery_failed = False
    user_service.get_email_preferences = AsyncMock(return_value=prefs)

    job = MagicMock()
    job.id = "job-123"
    job.function = "send_email_task"
    job.meta = {"priority": EmailPriority.LOW.value}
    job.kwargs = {}
    job.attempts = 1
    job.status = Status.NEW
    job.error = None
    job.queue = MagicMock()
    job.queue.enqueue = AsyncMock()

    return cast(
        CanterlotContext,
        {
            "job": job,
            "cache_repo": cache_repo,
            "user_service": user_service,
            "email_client": email_client,
            "dlq_queue": email_task_queue,
            "abort_job": False,
        },
    )


def describe_before_process_hook():

    async def it_returns_false_if_no_job_or_queue_exists(ctx):
        ctx["job"] = None
        result = await before_process_hook(ctx)
        assert result is False

        job_no_queue = MagicMock()
        job_no_queue.queue = None
        ctx["job"] = job_no_queue
        result = await before_process_hook(ctx)
        assert result is False

    async def it_postpones_low_priority_jobs_if_global_quota_lock_is_active(ctx, cache_repo):
        cache_repo.find.return_value = b"active"
        ctx["job"].meta = {"priority": EmailPriority.LOW.value}
        ctx["job"].kwargs = {"payload_str": "some-string"}

        result = await before_process_hook(ctx)

        assert result is False
        assert ctx.get("abort_job") is True
        ctx["job"].queue.enqueue.assert_awaited_once()

    async def it_allows_high_priority_jobs_through_global_quota_lock(ctx, cache_repo, base_payload):
        cache_repo.find.return_value = b"active"
        ctx["job"].meta = {"priority": EmailPriority.HIGH.value}
        ctx["job"].kwargs = {"payload_str": base_payload.model_dump_json()}

        result = await before_process_hook(ctx)
        assert result is True
        assert ctx.get("abort_job") is False

    async def it_returns_false_if_payload_is_missing_or_corrupted(ctx):
        ctx["job"].kwargs = {"payload_str": None}
        result = await before_process_hook(ctx)
        assert result is False

        ctx["job"].kwargs = {"payload_str": "{broken json"}
        result = await before_process_hook(ctx)
        assert result is False

    async def it_drops_stale_low_priority_tasks(ctx, base_payload):
        base_payload.created_at = datetime.now(UTC) - timedelta(hours=7)
        ctx["job"].meta = {"priority": EmailPriority.LOW.value}
        ctx["job"].kwargs = {"payload_str": base_payload.model_dump_json()}

        result = await before_process_hook(ctx)
        assert result is False

    async def it_postpones_jobs_if_recipient_operational_lock_is_active(ctx, user_service, base_payload):
        user_service.get_email_preferences.return_value.delivery_failed = True
        ctx["job"].meta = {"priority": EmailPriority.LOW.value}
        ctx["job"].kwargs = {"payload_str": base_payload.model_dump_json()}

        result = await before_process_hook(ctx)
        assert result is False
        assert ctx.get("abort_job") is True
        ctx["job"].queue.enqueue.assert_awaited_once()

    async def it_respects_rate_limiting_pacing_delay(ctx, base_payload, monkeypatch):
        settings_mock = MagicMock()
        settings_mock.email.dispatch_max_rps = 100.0  # 0.01s sleep
        monkeypatch.setattr("canterlot.worker.get_settings", lambda: settings_mock)

        ctx["job"].kwargs = {"payload_str": base_payload.model_dump_json()}

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await before_process_hook(ctx)
            assert result is True
            mock_sleep.assert_awaited_once_with(0.01)


def describe_after_process_hook():

    async def it_bails_early_if_no_job_exists(ctx):
        ctx["job"] = None
        await after_process_hook(ctx)
        ctx["dlq_queue"].enqueue.assert_not_awaited()

    async def it_ignores_successful_or_retryable_failures(ctx):
        ctx["job"].status = Status.FAILED
        ctx["job"].attempts = 1
        ctx["job"].kwargs = {"retries": 3}

        await after_process_hook(ctx)
        ctx["dlq_queue"].enqueue.assert_not_awaited()

    async def it_offloads_exhausted_jobs_to_the_dead_letter_queue(ctx):
        ctx["job"].status = Status.FAILED
        ctx["job"].attempts = 3
        ctx["job"].error = "Fatal Failure Traceback"
        ctx["job"].kwargs = {"retries": 3, "payload_str": "raw_payload"}

        await after_process_hook(ctx)
        ctx["dlq_queue"].enqueue.assert_awaited_once()


def describe_send_email_task():

    async def it_bails_immediately_if_abort_job_is_flagged(ctx):
        ctx["abort_job"] = True
        await send_email_task(ctx, "payload")
        ctx["email_client"].send.assert_not_awaited()

    async def it_falls_back_to_explicit_parsing_if_context_missing_payload(ctx, base_payload):
        ctx["email_payload"] = None
        raw_json = base_payload.model_dump_json()

        with patch("canterlot.worker.render_email_template") as mock_render:
            await send_email_task(ctx, raw_json)
            mock_render.assert_called_once()

    async def it_bails_if_fallback_parsing_fails(ctx):
        ctx["email_payload"] = None
        with patch("canterlot.worker.render_email_template") as mock_render:
            await send_email_task(ctx, "{invalid_json")
            mock_render.assert_not_called()

    async def it_skips_delivery_if_externally_suppressed(ctx, base_payload):
        ctx["email_payload"] = base_payload
        with patch(
            "canterlot.emails.core.policy.EmailPolicyEngine.is_external_suppressed",
            new_callable=AsyncMock,
        ) as mock_suppress:
            mock_suppress.return_value = True
            await send_email_task(ctx, "")
            ctx["email_client"].send.assert_not_awaited()

    async def it_skips_delivery_if_domain_policy_validation_fails(ctx, base_payload):
        ctx["email_payload"] = base_payload
        with patch("canterlot.emails.core.policy.EmailPolicyEngine.is_delivery_allowed") as mock_allow:
            mock_allow.return_value = False
            await send_email_task(ctx, "")
            ctx["email_client"].send.assert_not_awaited()

    async def it_triggers_global_circuit_breaker_on_quota_exhaustion(ctx, base_payload, email_client, cache_repo):
        ctx["email_payload"] = base_payload
        email_client.send.return_value.success = False
        email_client.send.return_value.disabled = True

        mock_rendered = MagicMock()
        mock_rendered.to_message = MagicMock()

        with (
            patch("canterlot.worker.render_email_template", return_value=mock_rendered),
            pytest.raises(RuntimeError, match="Upstream provider rate limit reached"),
        ):
            await send_email_task(ctx, "")

        cache_repo.save.assert_awaited_once_with(QUOTA_LOCK_KEY, {"status": "active"}, expire_seconds=3600)


def describe_worker_orchestration():

    async def it_runs_worker_context_lifecycle():
        settings_mock = MagicMock()
        settings_mock.environment = "test"
        settings_mock.db.redis_url.get_secret_value.return_value = "redis://localhost:6379"

        with (
            patch("canterlot.worker.get_settings", return_value=settings_mock),
            patch("canterlot.worker.setup_logging"),
            patch("canterlot.worker.get_email_client"),
            patch("canterlot.worker.DatabaseManager") as mock_db_mgr,
            patch("canterlot.worker.Redis") as mock_redis_cls,
            patch("canterlot.worker.Worker") as mock_worker_cls,
        ):
            mock_db_instance = MagicMock()
            mock_db_instance.__aenter__ = AsyncMock()
            mock_db_instance.__aexit__ = AsyncMock()
            mock_db_mgr.return_value = mock_db_instance

            mock_redis_client = MagicMock()
            mock_redis_client.aclose = AsyncMock()
            mock_redis_cls.from_url.return_value = mock_redis_client

            mock_worker_instance = MagicMock()
            mock_worker_instance.start = AsyncMock()
            mock_worker_cls.return_value = mock_worker_instance

            await run_worker()

            mock_worker_instance.start.assert_awaited_once()

    def it_executes_main_event_loop():
        with (
            patch("asyncio.run") as mock_run,
            patch("canterlot.worker.run_worker", new_callable=MagicMock) as mock_run_worker,
        ):
            mock_run_worker.return_value = "dummy_coro"

            main()

            mock_run_worker.assert_called_once()
            mock_run.assert_called_once_with("dummy_coro")
