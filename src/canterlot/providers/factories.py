from curl_cffi.requests import AsyncSession

from canterlot.config import get_settings
from canterlot.providers.annas import AnnaLinkProvider
from canterlot.providers.google import GoogleBookProvider
from canterlot.utils import get_logger

from .interfaces import BookProvider, LinkProvider

logger = get_logger(__name__)


def get_all_book_providers(session: AsyncSession) -> list[BookProvider]:
    api_key = get_settings().google_books_api_key

    if not api_key:
        logger.warn("Google Books API key is not configured; external book search/details will be unavailable")
        return []

    return [GoogleBookProvider(session, api_key)]


def get_all_link_providers(session: AsyncSession) -> list[LinkProvider]:
    return [AnnaLinkProvider(session)]
