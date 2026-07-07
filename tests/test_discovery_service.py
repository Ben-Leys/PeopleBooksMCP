from __future__ import annotations

import httpx
import pytest

from peoplebooks_mcp.config import DEFAULT_BOOKS, DEFAULT_DOC_VERSIONS
from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.discovery import DiscoveryError, discover_book
from peoplebooks_mcp.scraper.fetcher import PeopleBooksFetcher


def test_discover_book_fetches_home_and_book_navigation_then_queues_pages(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    home_html = "<html><a href='tpcr.html'>PeopleCode API Reference</a></html>"
    book_html = """
    <html>
      <body>
        <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
        <a href="tpcr/langref_ArrayClass.html">Array Class</a>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/index.html"):
            return httpx.Response(200, text=home_html, headers={"content-type": "text/html"})
        return httpx.Response(200, text=book_html, headers={"content-type": "text/html"})

    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(handler),
        delay_seconds=0,
        backoff_seconds=0,
    )

    with PeopleBooksRepository.connect(postgres_url) as repository:
        result = discover_book(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            book_seed=DEFAULT_BOOKS["tpcr"],
            fetcher=fetcher,
        )

        version = repository.get_doc_version_by_code("pt862")
        assert version is not None
        pages = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)

    assert result.pages_queued == 2
    assert [page.title for page in pages] == ["Application Class", "Array Class"]
    assert all(page.fetch_status == "queued" for page in pages)


def test_discover_book_fails_when_configured_book_link_is_absent() -> None:
    home_html = "<html><a href='tpcl.html'>PeopleCode Language Reference</a></html>"

    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=home_html)),
        delay_seconds=0,
        backoff_seconds=0,
    )

    with pytest.raises(DiscoveryError, match="PeopleCode API Reference"):
        discover_book(
            repository=object(),
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            book_seed=DEFAULT_BOOKS["tpcr"],
            fetcher=fetcher,
        )
