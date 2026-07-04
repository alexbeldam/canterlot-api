from unittest.mock import AsyncMock, MagicMock

import pytest
from curl_cffi.requests import AsyncSession

from canterlot.models.book import SearchParams
from canterlot.models.enums import ExtensionType, LinkProviderName
from canterlot.providers.annas import provider as provider_module
from canterlot.providers.annas.parser import SearchResult
from canterlot.providers.annas.provider import AnnaLinkProvider


def _search_result(md5: str = "abc123", **overrides) -> SearchResult:
    defaults = {
        "md5": md5,
        "title": "The Hobbit",
        "authors": ["J.R.R. Tolkien"],
        "languages": ["en"],
        "extension": ExtensionType.PDF,
        "url": "https://mirror.example.com/x.pdf",
    }
    return SearchResult.model_validate({**defaults, **overrides})


def _response(status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = ""
    if status_code != 200:
        response.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    return response


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def provider(session: AsyncMock) -> AnnaLinkProvider:
    return AnnaLinkProvider(session)


def describe_name():
    def it_reports_annas_archive_as_its_provider_name(provider: AnnaLinkProvider):
        assert provider.name == LinkProviderName.ANNAS


def describe_query_generation():
    async def it_issues_one_search_per_generated_query_variation(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [])
        session.get.return_value = _response()

        await provider.find_links(SearchParams(title="The Hobbit", isbn_13="9783161484100"))

        assert session.get.await_count == 2

    async def it_includes_preferred_languages_and_extensions_in_the_request(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [])
        session.get.return_value = _response()

        await provider.find_links(SearchParams(title="The Hobbit", languages=["en"], extensions=[ExtensionType.EPUB]))

        params = session.get.call_args.kwargs["params"]
        assert params["lang"] == ["en"]
        assert params["ext"] == ["epub"]

    async def it_defaults_to_all_extensions_when_none_are_specified(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [])
        session.get.return_value = _response()

        await provider.find_links(SearchParams(title="The Hobbit"))

        params = session.get.call_args.kwargs["params"]
        assert set(params["ext"]) == {e.value for e in ExtensionType}

    async def it_returns_no_queries_and_no_candidates_for_an_empty_search(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [])

        results = await provider.find_links(SearchParams())

        assert results == []
        session.get.assert_not_called()


def describe_result_merging():
    async def it_dedupes_candidates_sharing_the_same_md5_across_queries(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        shared = _search_result(md5="shared")
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [shared])
        session.get.return_value = _response()

        results = await provider.find_links(SearchParams(title="The Hobbit", isbn_13="9783161484100"))

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].md5 == "shared"

    async def it_tolerates_one_query_failing_while_keeping_results_from_others(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        good_result = _search_result(md5="good")
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [good_result])

        async def fake_get(_url, params=None):
            if params and params.get("q") == "9783161484100":
                raise RuntimeError("mirror unreachable")
            return _response()

        session.get.side_effect = fake_get

        results = await provider.find_links(SearchParams(title="The Hobbit", isbn_13="9783161484100"))

        assert [r.md5 for r in results if isinstance(r, SearchResult)] == ["good"]

    async def it_raises_for_a_non_200_response_which_is_treated_as_a_failed_query(
        monkeypatch: pytest.MonkeyPatch, provider: AnnaLinkProvider, session: AsyncMock
    ):
        monkeypatch.setattr(provider_module, "parse_response", lambda _response: [])
        session.get.return_value = _response(status_code=500)

        results = await provider.find_links(SearchParams(title="The Hobbit"))

        assert results == []
