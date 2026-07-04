from unittest.mock import AsyncMock

from curl_cffi.requests import AsyncSession

from canterlot.providers.annas.provider import AnnaLinkProvider
from canterlot.providers.factories import get_all_book_providers, get_all_link_providers
from canterlot.providers.google import GoogleBookProvider


def describe_get_all_book_providers():
    def it_returns_a_google_book_provider():
        providers = get_all_book_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], GoogleBookProvider)


def describe_get_all_link_providers():
    def it_returns_an_annas_archive_link_provider():
        providers = get_all_link_providers(AsyncMock(spec=AsyncSession))

        assert len(providers) == 1
        assert isinstance(providers[0], AnnaLinkProvider)
