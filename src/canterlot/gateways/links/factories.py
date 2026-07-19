from curl_cffi.requests import AsyncSession

from .annas import AnnaLinkProvider
from .interfaces import LinkProvider


def get_all_link_providers(session: AsyncSession) -> list[LinkProvider]:
    return [AnnaLinkProvider(session)]
