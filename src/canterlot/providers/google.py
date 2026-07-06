from curl_cffi.requests import AsyncSession
from fastapi import status
from pydantic import HttpUrl

from canterlot.config import get_settings
from canterlot.dto.book import BookDetails, BookSearchResult
from canterlot.models.book import BookProviderIdentifier, SearchParams
from canterlot.models.enums import BookProviderName
from canterlot.utils import get_logger
from canterlot.utils.format import HttpsUrl

from .interfaces import BookProvider, ProviderSearchResponse

logger = get_logger(__name__)


class GoogleBookProvider(BookProvider):
    def __init__(self, session: AsyncSession):
        self.__session = session

    @property
    def name(self) -> BookProviderName:
        return BookProviderName.GOOGLE

    async def fetch_volumes(self, search: SearchParams, start_index: int, max_results: int) -> ProviderSearchResponse:
        params = self.__build_params(search, start_index, max_results)

        log = logger.bind(
            provider=self.name,
            search_query=params["q"],
            start_index=start_index,
            max_results=max_results,
        )
        log.info("Dispatching HTTP GET request to Google Books API volumes endpoint")

        response = await self.__session.get("https://www.googleapis.com/books/v1/volumes", params=params)

        log = log.bind(http_status_code=response.status_code)

        if response.status_code != status.HTTP_200_OK:
            log.error(
                "Google Books API returned an invalid operational status code",
                response_body=response.text[:500],
            )
            return {"books": [], "total_results": 0}

        data = response.json()
        items = data.get("items", [])
        total_results = data.get("totalItems", 0)

        log.debug(
            "Upstream data successfully fetched",
            items_payload_count=len(items),
            api_reported_total_items=total_results,
        )

        results = [book for item in items if (book := self.__map_volume_item(item, log)) is not None]

        log.info(
            "Successfully parsed and converted Google Books API volumes search dataset",
            mapped_books_count=len(results),
        )
        return {"books": results, "total_results": total_results}

    def __map_volume_item(self, item: dict, log) -> BookSearchResult | None:
        item_id = item.get("id")
        if not isinstance(item_id, str):
            log.debug("Skipping malformed volume in Google Books API response", volume_id=item_id)
            return None

        volume_info = item.get("volumeInfo", {})
        isbn_10, isbn_13 = self.__parse_isbn(volume_info.get("industryIdentifiers", []))

        try:
            return BookSearchResult(
                id=BookProviderIdentifier(provider=self.name, book_id=item_id),
                title=volume_info.get("title"),
                authors=volume_info.get("authors", []),
                year=self.__extract_year(volume_info),
                cover_url=self.__extract_cover_url(volume_info),
                languages=[volume_info["language"]] if volume_info.get("language") else [],
                isbn_10=isbn_10,
                isbn_13=isbn_13,
            )
        except ValueError:
            log.debug("Skipping malformed volume in Google Books API response", volume_id=item_id)
            return None

    def __extract_cover_url(self, volume_info: dict) -> HttpsUrl | None:
        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail") or None

        if not cover_url:
            return None

        if cover_url.startswith("http://"):
            cover_url = cover_url.replace("http://", "https://")

        return HttpUrl(cover_url)

    def __extract_year(self, volume_info: dict) -> int | None:
        published_date = volume_info.get("publishedDate", "")
        year_slice = published_date[:4] if published_date else ""

        return int(year_slice) if year_slice.isdigit() else None

    async def fetch_volume_details(self, provider_book_id: str) -> BookDetails | None:
        api_key = get_settings().google_books_api_key
        url = f"https://www.googleapis.com/books/v1/volumes/{provider_book_id}?key={api_key}"

        log = logger.bind(provider=self.name, volume_id=provider_book_id)
        log.info("Dispatching HTTP GET request to Google Books API volume details endpoint")

        response = await self.__session.get(url)

        log = log.bind(http_status_code=response.status_code)

        if response.status_code != status.HTTP_200_OK:
            log.warn("Failed to fetch volume details card from Google Books API", response_body=response.text[:500])
            return None

        data = response.json()
        volume_info = data.get("volumeInfo", {})

        log.info("Successfully fetched and extracted volume details context")
        return BookDetails(
            description=volume_info.get("description") or None,
            page_count=volume_info.get("pageCount"),
            categories=volume_info.get("categories", []),
        )

    def __build_params(self, params: SearchParams, start_index: int, max_results: int) -> dict:
        isbn = params.isbn_13 or params.isbn_10

        if isbn:
            query_parts = [f"isbn:{isbn}"]
        else:
            query_parts = []
            if params.title:
                query_parts.append(f'intitle:"{params.title}"')

            query_parts.extend(f'inauthor:"{author}"' for author in params.authors)

        return {
            "q": " ".join(query_parts),
            "startIndex": start_index,
            "maxResults": max_results,
            "key": get_settings().google_books_api_key,
        }

    def __parse_isbn(self, identifiers: list[dict]) -> tuple[str | None, str | None]:
        isbn_10 = None
        isbn_13 = None

        for identifier in identifiers:
            identifier_str = identifier.get("identifier")

            if not isinstance(identifier_str, str):
                continue

            id_type = identifier.get("type")

            if id_type == "ISBN_13":
                isbn_13 = identifier_str
            elif id_type == "ISBN_10":
                isbn_10 = identifier_str

        return isbn_10, isbn_13
