from unittest.mock import AsyncMock

import pytest

from canterlot.gateways import BookProvider, LinkProvider
from canterlot.types import BookProviderName, LinkProviderName


@pytest.fixture
def book_provider() -> AsyncMock:
    provider = AsyncMock(spec=BookProvider)
    provider.name = BookProviderName.GOOGLE

    return provider


@pytest.fixture
def link_provider() -> AsyncMock:
    provider = AsyncMock(spec=LinkProvider)
    provider.name = LinkProviderName.ANNAS

    return provider
