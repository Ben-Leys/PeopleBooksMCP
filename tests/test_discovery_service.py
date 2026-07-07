from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from peoplebooks_mcp.config import DEFAULT_BOOKS, DEFAULT_DOC_VERSIONS
from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.discovery import (
    DiscoveryError,
    DiscoveryProgress,
    discover_book,
    discover_products_tree,
)
from peoplebooks_mcp.scraper.fetcher import PeopleBooksFetcher


def test_discover_products_tree_uses_products_category_chain_without_postgres() -> None:
    class FakeRepository:
        def __init__(self) -> None:
            self.nav_nodes: list[dict[str, object]] = []
            self.pages: list[dict[str, object]] = []
            self._next_id = 1

        def upsert_doc_version(self, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(id=100, **kwargs)

        def upsert_book(self, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(id=200, **kwargs)

        def upsert_nav_node(self, **kwargs) -> SimpleNamespace:
            record = {"id": self._next_id, **kwargs}
            self._next_id += 1
            self.nav_nodes.append(record)
            return SimpleNamespace(**record)

        def queue_page(self, **kwargs) -> SimpleNamespace:
            self.pages.append(kwargs)
            return SimpleNamespace(id=len(self.pages), **kwargs)

    home_html = """
    <html>
      <nav id="contents">
        <ul>
          <li>
            Products
            <ul>
              <li>
                Development Tools
                <ul>
                  <li><a href="tpcr.html?focusnode=tpcr">PeopleCode API Reference</a></li>
                </ul>
              </li>
            </ul>
          </li>
        </ul>
      </nav>
    </html>
    """
    book_html = """
    <html><body>
      <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/index.html"):
            return httpx.Response(200, text=home_html, headers={"content-type": "text/html"})
        return httpx.Response(200, text=book_html, headers={"content-type": "text/html"})

    repository = FakeRepository()
    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(handler),
        delay_seconds=0,
        backoff_seconds=0,
    )

    result = discover_products_tree(
        repository=repository,
        version_seed=DEFAULT_DOC_VERSIONS["pt862"],
        fetcher=fetcher,
    )

    assert result.books_discovered == 1
    assert result.pages_queued == 1
    stored_nav_nodes = [
        (node["stable_id"], node["parent_id"], node["node_type"]) for node in repository.nav_nodes
    ]
    assert stored_nav_nodes == [
        ("tpcr/products", None, "category"),
        ("tpcr/products/development_tools", 1, "category"),
        ("tpcr/root", 2, "book"),
        ("tpcr/langref_applicationclass", 3, "page"),
    ]
    assert repository.pages[0]["normalized_path"].endswith(
        "/pt862pbr3/eng/pt/tpcr/langref_ApplicationClass.html"
    )


def test_discover_products_tree_reports_progress_for_each_book() -> None:
    class FakeRepository:
        def __init__(self) -> None:
            self._next_id = 1

        def upsert_doc_version(self, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(id=100, **kwargs)

        def upsert_book(self, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(id=200, **kwargs)

        def upsert_nav_node(self, **kwargs) -> SimpleNamespace:
            record = SimpleNamespace(id=self._next_id, **kwargs)
            self._next_id += 1
            return record

        def queue_page(self, **kwargs) -> SimpleNamespace:
            return SimpleNamespace(id=300, **kwargs)

    home_html = """
    <html>
      <nav id="contents">
        <ul>
          <li>
            Products
            <ul>
              <li><a href="tpcr.html?focusnode=tpcr">PeopleCode API Reference</a></li>
            </ul>
          </li>
        </ul>
      </nav>
    </html>
    """
    book_html = """
    <html><body>
      <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
    </body></html>
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
    progress_events: list[DiscoveryProgress] = []

    discover_products_tree(
        repository=FakeRepository(),
        version_seed=DEFAULT_DOC_VERSIONS["pt862"],
        fetcher=fetcher,
        progress=progress_events.append,
    )

    assert [
        (
            event.books_processed,
            event.total_books,
            event.nav_nodes_discovered,
            event.pages_queued,
        )
        for event in progress_events
    ] == [
        (0, 1, 0, 0),
        (1, 1, 3, 1),
    ]


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


def test_discover_products_tree_discovers_multiple_books_and_category_chains(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    home_html = """
    <html>
      <nav id="contents">
        <ul>
          <li>
            Products
            <ul>
              <li>
                Development Tools
                <ul>
                  <li>
                    PeopleCode
                    <ul>
                      <li><a href="tpcr.html?focusnode=tpcr">PeopleCode API Reference</a></li>
                      <li><a href="tpcl.html?focusnode=tpcl">PeopleCode Language Reference</a></li>
                    </ul>
                  </li>
                </ul>
              </li>
            </ul>
          </li>
        </ul>
      </nav>
    </html>
    """
    book_html_by_code = {
        "tpcr": """
        <html><body>
          <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
          <a href="tpcr/langref_ArrayClass.html">Array Class</a>
        </body></html>
        """,
        "tpcl": """
        <html><body>
          <a href="tpcl/langref_DeclareFunction.html">Declare Function</a>
        </body></html>
        """,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/index.html"):
            return httpx.Response(200, text=home_html, headers={"content-type": "text/html"})
        book_code = request.url.path.rsplit("/", maxsplit=1)[-1].split(".", maxsplit=1)[0]
        return httpx.Response(
            200,
            text=book_html_by_code[book_code],
            headers={"content-type": "text/html"},
        )

    fetcher = PeopleBooksFetcher(
        transport=httpx.MockTransport(handler),
        delay_seconds=0,
        backoff_seconds=0,
    )

    with PeopleBooksRepository.connect(postgres_url) as repository:
        result = discover_products_tree(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            fetcher=fetcher,
        )

        version = repository.get_doc_version_by_code("pt862")
        assert version is not None
        books = repository.list_books(doc_version_id=version.id)
        pages = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)
        nav_nodes = repository.list_nav_nodes(doc_version_id=version.id)

    assert result.books_discovered == 2
    assert result.pages_queued == 3
    assert [book.code for book in books] == ["tpcl", "tpcr"]
    assert [page.title for page in pages] == [
        "Application Class",
        "Array Class",
        "Declare Function",
    ]

    tpcr_chain = [
        (node.stable_id, node.title, node.node_type)
        for node in nav_nodes
        if node.stable_id.startswith("tpcr/")
    ]
    assert tpcr_chain[:4] == [
        ("tpcr/products", "Products", "category"),
        ("tpcr/products/development_tools", "Development Tools", "category"),
        ("tpcr/products/development_tools/peoplecode", "PeopleCode", "category"),
        ("tpcr/root", "PeopleCode API Reference", "book"),
    ]


def test_discover_products_tree_rerun_is_idempotent(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    home_html = """
    <html>
      <nav id="contents">
        <ul>
          <li>
            Products
            <ul>
              <li>
                Development Tools
                <ul>
                  <li><a href="tpcr.html?focusnode=tpcr">PeopleCode API Reference</a></li>
                </ul>
              </li>
            </ul>
          </li>
        </ul>
      </nav>
    </html>
    """
    book_html = """
    <html><body>
      <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
    </body></html>
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
        first_result = discover_products_tree(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            fetcher=fetcher,
        )
        version = repository.get_doc_version_by_code("pt862")
        assert version is not None
        first_pages = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)
        first_nav_nodes = repository.list_nav_nodes(doc_version_id=version.id)

        second_result = discover_products_tree(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            fetcher=fetcher,
        )
        second_pages = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)
        second_nav_nodes = repository.list_nav_nodes(doc_version_id=version.id)

    assert first_result == second_result
    assert [page.id for page in second_pages] == [page.id for page in first_pages]
    assert [node.id for node in second_nav_nodes] == [node.id for node in first_nav_nodes]
    assert [(node.stable_id, node.parent_id) for node in second_nav_nodes] == [
        (node.stable_id, node.parent_id) for node in first_nav_nodes
    ]


def test_full_products_tree_discovery_preserves_existing_seeded_page(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    seed_home_html = "<html><a href='tpcr.html'>PeopleCode API Reference</a></html>"
    products_home_html = """
    <html>
      <nav id="contents">
        <ul>
          <li>
            Products
            <ul>
              <li>
                Development Tools
                <ul>
                  <li><a href="tpcr.html?focusnode=tpcr">PeopleCode API Reference</a></li>
                </ul>
              </li>
            </ul>
          </li>
        </ul>
      </nav>
    </html>
    """
    book_html = """
    <html><body>
      <a href="tpcr/langref_ApplicationClass.html">Application Class</a>
    </body></html>
    """
    home_html = seed_home_html

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
        discover_book(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            book_seed=DEFAULT_BOOKS["tpcr"],
            fetcher=fetcher,
        )
        version = repository.get_doc_version_by_code("pt862")
        assert version is not None
        seeded_page = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)[0]

        home_html = products_home_html
        result = discover_products_tree(
            repository=repository,
            version_seed=DEFAULT_DOC_VERSIONS["pt862"],
            fetcher=fetcher,
        )
        refreshed_page = repository.list_next_queued_pages(doc_version_id=version.id, limit=10)[0]
        nav_nodes = repository.list_nav_nodes(doc_version_id=version.id)

    assert result.pages_queued == 1
    assert refreshed_page.id == seeded_page.id
    assert refreshed_page.normalized_path == seeded_page.normalized_path
    assert any(node.stable_id == "tpcr/products/development_tools" for node in nav_nodes)


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
