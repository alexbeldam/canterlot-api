from types import SimpleNamespace
from typing import cast

from curl_cffi.requests import Response

from canterlot.models.enums import ExtensionType
from canterlot.providers.annas.parser import parse_response


def _response(html: str, url: str = "https://annas-archive.gl/search?q=hobbit") -> Response:
    return cast(Response, SimpleNamespace(content=html.encode("utf-8"), url=url))


def describe_parse_response():
    def it_parses_a_well_formed_result_card_with_an_author():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
          <a href="/search?q=J.R.R.+Tolkien">J.R.R. Tolkien</a>
          <div>English [en] &middot; pdf &middot; 2.5MB</div>
        </div>
        """
        results = parse_response(_response(html))

        assert len(results) == 1
        result = results[0]
        assert result.md5 == "abc123"
        assert result.title == "The Hobbit"
        assert str(result.url) == "https://annas-archive.gl/md5/abc123"
        assert result.authors == ["J.R.R. Tolkien"]
        assert result.languages == ["en"]
        assert result.extension == ExtensionType.PDF

    def it_parses_a_result_without_an_author_sibling():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
          <div>[en] &middot; epub</div>
        </div>
        """
        results = parse_response(_response(html))

        assert len(results) == 1
        assert results[0].authors == []
        assert results[0].extension == ExtensionType.EPUB

    def it_ignores_anchors_that_do_not_link_to_a_md5_page():
        html = """
        <div>
          <a href="/some/other/page">Not A Book</a>
          <div>[en] &middot; pdf</div>
        </div>
        """
        assert parse_response(_response(html)) == []

    def it_ignores_a_md5_anchor_with_no_visible_text():
        html = """
        <div>
          <a href="/md5/abc123"></a>
          <div>[en] &middot; pdf</div>
        </div>
        """
        assert parse_response(_response(html)) == []

    def it_skips_a_result_with_no_metadata_div():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
        </div>
        """
        assert parse_response(_response(html)) == []

    def it_skips_a_result_whose_metadata_does_not_match_the_expected_pattern():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
          <div>No usable metadata here</div>
        </div>
        """
        assert parse_response(_response(html)) == []

    def it_skips_a_result_with_an_unparsable_language_tag():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
          <div>Weird [???] &middot; pdf</div>
        </div>
        """
        assert parse_response(_response(html)) == []

    def it_resolves_the_book_url_against_the_response_hostname():
        html = """
        <div>
          <a href="/md5/xyz789">Another Book</a>
          <div>[en] &middot; pdf</div>
        </div>
        """
        results = parse_response(_response(html, url="https://annas-archive.pk/search?q=another"))

        assert str(results[0].url) == "https://annas-archive.pk/md5/xyz789"

    def it_parses_multiple_languages_from_separate_bracketed_segments():
        html = """
        <div>
          <a href="/md5/abc123">The Hobbit</a>
          <div>English [en] &middot; Russian [ru] &middot; PDF</div>
        </div>
        """
        results = parse_response(_response(html))

        assert len(results) == 1
        assert results[0].languages == ["en", "ru"]
        assert results[0].extension == ExtensionType.PDF

    def it_parses_multiple_results_on_the_same_page():
        html = """
        <div>
          <a href="/md5/book1">First Book</a>
          <div>[en] &middot; pdf</div>
        </div>
        <div>
          <a href="/md5/book2">Second Book</a>
          <div>[es] &middot; epub</div>
        </div>
        """
        results = parse_response(_response(html))

        assert [r.md5 for r in results] == ["book1", "book2"]
