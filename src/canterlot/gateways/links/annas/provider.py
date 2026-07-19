import asyncio
from typing import ClassVar
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession
from fastapi import status

from canterlot.models.book import LinkCandidate, SearchParams
from canterlot.types import ExtensionType, LinkProviderName
from canterlot.utils import get_logger
from canterlot.utils.mirror import MirrorPool

from ..interfaces import LinkProvider
from .parser import SearchResult, parse_response

type SearchResponse = list[SearchResult] | BaseException
type ParamList = dict[str, str | list[str]]

logger = get_logger(__name__)


class AnnaLinkProvider(LinkProvider):
    _MIRROR_URLS: ClassVar[list[str]] = [
        "https://annas-archive.gl",
        "https://annas-archive.pk",
        "https://annas-archive.gd",
    ]

    def __init__(self, session: AsyncSession):
        self.__pool = MirrorPool(AnnaLinkProvider._MIRROR_URLS)
        self.__session = session

    @property
    def name(self) -> LinkProviderName:
        return LinkProviderName.ANNAS

    async def find_links(self, params: SearchParams) -> list[LinkCandidate]:
        log = logger.bind(provider=self.name)
        log.info("Initiating search for link candidates across all generated queries")

        responses = await self.__search_all(params)
        candidates = await self.__merge_responses(responses)

        log.info(
            "Link search completed successfully",
            total_distinct_candidates=len(candidates),
        )
        return candidates

    def __build_params(self, search: SearchParams) -> list[ParamList]:
        queries: list[str] = []

        if search.isbn_13:
            queries.append(search.isbn_13)
        if search.isbn_10:
            queries.append(search.isbn_10)
        if search.title:
            query = search.title

            if search.authors:
                query += " " + " ".join(search.authors)

            queries.append(query)

        target_extensions = search.extensions if search.extensions else list(ExtensionType)
        extensions = [e.value for e in target_extensions]

        params_list: list[dict[str, str | list[str]]] = []

        for query in queries:
            params: dict[str, str | list[str]] = {
                "q": query,
                "sort": "most_relevant",
            }

            if search.languages:
                params["lang"] = search.languages
            if extensions:
                params["ext"] = extensions

            params_list.append(params)

        return params_list

    async def __search(self, base_url: str, params: ParamList) -> list[SearchResult]:
        log = logger.bind(
            provider=self.name,
            base_url=base_url,
            search_query=params.get("q"),
        )
        log.info("Dispatching HTTP GET request to Anna's Archive mirror endpoint")

        try:
            response = await self.__session.get(urljoin(base_url, "search"), params=params)
            log = log.bind(http_status_code=response.status_code)

            if response.status_code != status.HTTP_200_OK:
                log.error(
                    "Upstream mirror returned an invalid operational status code",
                    response_body=response.text[:500],
                )
                response.raise_for_status()

            results = parse_response(response)

            log.debug(
                "Upstream mirror data successfully fetched and parsed",
                items_payload_count=len(results),
            )
            return results
        except Exception as e:
            log.error(
                "Request to upstream mirror failed with an unhandled exception",
                exception_message=str(e),
            )
            raise e

    async def __search_all(self, search: SearchParams) -> list[SearchResponse]:
        generated_params = self.__build_params(search)

        log = logger.bind(provider=self.name)
        log.debug("Generated search parameter permutations", query_variations_count=len(generated_params))

        tasks = [
            self.__pool.execute(
                self.__search,
                params,
            )
            for params in generated_params
        ]

        return await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

    async def __merge_responses(self, responses: list[SearchResponse]) -> list[LinkCandidate]:
        dedup: dict[str, LinkCandidate] = {}
        exception_count = 0

        for response in responses:
            if isinstance(response, BaseException):
                exception_count += 1
                continue

            for link in response:
                dedup.setdefault(link.md5, link)

        if exception_count > 0:
            logger.bind(provider=self.name).warn(
                "Some search operations encountered errors during concurrent execution",
                failed_tasks_count=exception_count,
            )

        return list(dedup.values())
