from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from redis.asyncio import Redis
from saq import Queue


def make_test_request(client_host: str | None = "203.0.113.5") -> Request:
    req = MagicMock(spec=Request)
    req.client = SimpleNamespace(host=client_host) if client_host else None
    req.app = SimpleNamespace(
        state=SimpleNamespace(
            redis_client=AsyncMock(spec=Redis),
            email_task_queue=AsyncMock(spec=Queue),
        )
    )
    return cast(Request, req)


@pytest.fixture
def make_request():
    """Factory fixture for creating test Request objects."""
    return make_test_request
