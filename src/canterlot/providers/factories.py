from curl_cffi.requests import AsyncSession

from canterlot.providers.annas import AnnaLinkProvider
from canterlot.providers.google import GoogleBookProvider

from .interfaces import BookProvider, LinkProvider


def get_all_book_providers(session: AsyncSession) -> list[BookProvider]:
    return [GoogleBookProvider(session)]


def get_all_link_providers(session: AsyncSession) -> list[LinkProvider]:
    return [AnnaLinkProvider(session)]
