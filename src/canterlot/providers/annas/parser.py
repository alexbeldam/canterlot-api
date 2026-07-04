import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import Response
from pydantic import HttpUrl

from canterlot.models.book import LinkCandidate
from canterlot.models.enums import ExtensionType
from canterlot.utils import get_logger

logger = get_logger(__name__)


class SearchResult(LinkCandidate):
    md5: str


_EXTENSION_PATTERN = "|".join(re.escape(ext.value) for ext in ExtensionType)

_METADATA_RE = re.compile(
    rf"""
    \[
        (?P<lang>[^\]]+)
    \]
    \s+·\s+
    (?P<ext>{_EXTENSION_PATTERN})
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_response(response: Response) -> list[SearchResult]:
    soup = BeautifulSoup(response.content, "lxml")

    raw_results: list[Tag] = soup.find_all(__is_title_anchor)
    results = []

    for r in raw_results:
        result = __parse_result(r, str(response.url))

        if result:
            results.append(result)

    return results


def __parse_result(node: Tag, req_url: str) -> SearchResult | None:
    title = node.get_text(strip=True)
    href = node.get("href")

    if not isinstance(href, str):  # pragma: no cover
        return None

    md5 = href.removeprefix("/md5/")
    base_url = f"https://{urlsplit(req_url).hostname}"
    url = urljoin(base_url, href)
    sibling = node.find_next_sibling("a", href=__is_search_href)
    authors = [sibling.get_text(strip=True)] if sibling else []

    parent = node.parent

    if not isinstance(parent, Tag):  # pragma: no cover
        return None

    metadata = parent.find_next(__is_metadata_div)

    if not isinstance(metadata, Tag):
        return None

    match = _METADATA_RE.search(metadata.get_text(" ", strip=True))

    if match is None:  # pragma: no cover
        return None

    try:
        return SearchResult(
            md5=md5,
            title=title,
            url=HttpUrl(url),
            authors=authors,
            language=match["lang"],
            extension=ExtensionType(match["ext"].lower()),
        )
    except ValueError:
        logger.debug("Skipping malformed scraped search result", md5=md5, title=title)
        return None


def __is_title_anchor(tag: Tag) -> bool:
    if tag.name != "a":
        return False

    href = tag.get("href")
    if not isinstance(href, str) or not href.startswith("/md5/"):
        return False

    return bool(tag.get_text(strip=True))


def __is_search_href(href: str | None) -> bool:
    return href is not None and "search?q" in href


def __is_metadata_div(tag: Tag) -> bool:
    return tag.name == "div" and _METADATA_RE.search(tag.get_text(" ", strip=True)) is not None
