from unittest.mock import AsyncMock

from curl_cffi.requests import AsyncSession

from canterlot.gateways.links.annas import AnnaLinkProvider
from canterlot.gateways.links.factories import get_all_link_providers


def describe_get_all_link_providers():
    def it_returns_an_annas_archive_link_provider():
        providers = get_all_link_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], AnnaLinkProvider)
