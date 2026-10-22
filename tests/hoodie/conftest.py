import contextlib
from collections.abc import Iterator

import pytest
from pymongo import AsyncMongoClient, monitoring

from tests.mongo_integration import init_hoodied_beanie  # noqa: F401


class CommandRecorder(monitoring.CommandListener):
    # Captures wire commands during an opt-in window via pymongo's own monitoring API, so
    # tests assert call counts without reaching into hoodie's internals.
    def __init__(self) -> None:
        self.events: list[monitoring.CommandStartedEvent] = []
        self._recording = False

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        if self._recording:
            self.events.append(event)

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass

    @contextlib.contextmanager
    def recording(self) -> Iterator[list[monitoring.CommandStartedEvent]]:
        self.events = []
        self._recording = True
        try:
            yield self.events
        finally:
            self._recording = False


_command_recorder = CommandRecorder()
# Registered globally rather than passed as the shared hoodie_client's event_listeners=,
# since that client is now defined once in tests/mongo_integration.py for both integration
# tiers. Must run at import time (collection), before the session-scoped client is created.
monitoring.register(_command_recorder)


@pytest.fixture
def command_recorder(hoodie_client: AsyncMongoClient) -> CommandRecorder:  # noqa: ARG001
    return _command_recorder
