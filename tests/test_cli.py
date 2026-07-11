from typer.testing import CliRunner

from peoplebooks_mcp.cli import app
from peoplebooks_mcp.config import AppConfig, BookSeed, DocVersionSeed, RuntimeSettings
from peoplebooks_mcp.indexing import IndexResult
from peoplebooks_mcp.repositories import StatusCounts
from peoplebooks_mcp.scraper.discovery import DiscoveryProgress, DiscoveryResult
from peoplebooks_mcp.scraper.scrape import ReparseResult, ScrapeProgress, ScrapeResult


def test_cli_help_lists_planned_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["discover", "scrape", "status", "reparse", "index", "serve-mcp"]:
        assert command in result.output


def test_discover_help_shows_seed_options() -> None:
    result = CliRunner().invoke(app, ["discover", "--help"])

    assert result.exit_code == 0
    assert "--version" in result.output
    assert "--book" in result.output
    assert "--all-books" in result.output


def test_discover_command_runs_configured_discovery(monkeypatch) -> None:
    calls = []

    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_discover_book(**kwargs) -> DiscoveryResult:
        calls.append(kwargs)
        return DiscoveryResult(nav_nodes_discovered=2, pages_queued=2)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.discover_book", fake_discover_book)

    result = CliRunner().invoke(app, ["discover"])

    assert result.exit_code == 0
    assert "Discovered 2 navigation nodes" in result.output
    assert "queued 2 pages" in result.output
    assert calls[0]["version_seed"].code == "pt862"
    assert calls[0]["book_seed"].code == "tpcr"


def test_discover_command_prints_progress_counter(monkeypatch) -> None:
    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_discover_book(**kwargs) -> DiscoveryResult:
        kwargs["progress"](
            DiscoveryProgress(
                books_processed=0,
                total_books=1,
                nav_nodes_discovered=0,
                pages_queued=0,
            )
        )
        kwargs["progress"](
            DiscoveryProgress(
                books_processed=1,
                total_books=1,
                nav_nodes_discovered=2,
                pages_queued=2,
            )
        )
        return DiscoveryResult(nav_nodes_discovered=2, pages_queued=2)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.discover_book", fake_discover_book)

    result = CliRunner().invoke(app, ["discover"])

    assert result.exit_code == 0
    assert "Discovering books: 0/1; navigation nodes 0; queued 0 pages" in result.output
    assert "Discovering books: 1/1; navigation nodes 2; queued 2 pages" in result.output


def test_discover_command_can_run_full_products_tree_discovery(monkeypatch) -> None:
    calls = []

    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_discover_products_tree(**kwargs) -> DiscoveryResult:
        calls.append(kwargs)
        return DiscoveryResult(nav_nodes_discovered=6, pages_queued=3, books_discovered=2)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.discover_products_tree",
        fake_discover_products_tree,
    )

    result = CliRunner().invoke(app, ["discover", "--all-books"])

    assert result.exit_code == 0
    assert "Discovered 2 books; 6 navigation nodes; queued 3 pages." in result.output
    assert calls[0]["version_seed"].code == "pt862"
    assert calls[0]["book_codes"] is None


def test_discover_rejects_book_option_with_all_books(monkeypatch) -> None:
    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)

    result = CliRunner().invoke(app, ["discover", "--all-books", "--book", "unknown"])

    assert result.exit_code == 2
    assert "--book cannot be combined with --all-books" in result.output


def test_status_command_prints_lifecycle_counts(monkeypatch) -> None:
    class FakeVersion:
        id = 123

    class FakeRepository:
        def get_doc_version_by_code(self, code: str) -> FakeVersion:
            return FakeVersion()

        def get_status_counts(self, *, doc_version_id: int) -> StatusCounts:
            assert doc_version_id == 123
            return StatusCounts(
                discovered=4,
                queued=1,
                fetched=1,
                failed=1,
                parsed=1,
                indexed=0,
            )

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "total discovered pages: 4" in result.output
    assert "current lifecycle states:" in result.output
    assert "fetched, awaiting parse: 1" in result.output
    assert "parsed, awaiting index: 1" in result.output
    assert "indexed: 0" in result.output


def test_scrape_command_runs_configured_scrape(monkeypatch) -> None:
    calls = []

    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_scrape_pages(**kwargs) -> ScrapeResult:
        calls.append(kwargs)
        return ScrapeResult(scraped=2, failed=1, parsed=2)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.scrape_pages", fake_scrape_pages)

    result = CliRunner().invoke(app, ["scrape", "--limit", "3"])

    assert result.exit_code == 0
    assert "Scraped 2 pages" in result.output
    assert "failed 1" in result.output
    assert "parsed 2" in result.output
    assert calls[0]["version_code"] == "pt862"
    assert calls[0]["limit"] == 3


def test_scrape_command_prints_progress_counter(monkeypatch) -> None:
    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_scrape_pages(**kwargs) -> ScrapeResult:
        kwargs["progress"](
            ScrapeProgress(
                pages_processed=0,
                total_pages=3,
                scraped=0,
                failed=0,
                parsed=0,
            )
        )
        kwargs["progress"](
            ScrapeProgress(
                pages_processed=1,
                total_pages=3,
                scraped=1,
                failed=0,
                parsed=1,
            )
        )
        return ScrapeResult(scraped=1, failed=0, parsed=1)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.scrape_pages", fake_scrape_pages)

    result = CliRunner().invoke(app, ["scrape", "--limit", "3"])

    assert result.exit_code == 0
    assert "Scraping pages: 0/3; scraped 0; failed 0; parsed 0" in result.output
    assert "Scraping pages: 1/3; scraped 1; failed 0; parsed 1" in result.output


def test_reparse_command_runs_configured_reparse(monkeypatch) -> None:
    calls = []

    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_reparse_pages(**kwargs) -> ReparseResult:
        calls.append(kwargs)
        return ReparseResult(reparsed=4)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.reparse_pages", fake_reparse_pages)

    result = CliRunner().invoke(
        app,
        ["reparse", "--parser-version", "parser-v2"],
    )

    assert result.exit_code == 0
    assert "Reparsed 4 pages" in result.output
    assert calls[0]["version_code"] == "pt862"
    assert calls[0]["parser_version"] == "parser-v2"


def test_index_command_runs_configured_index(monkeypatch) -> None:
    calls = []

    class FakeRepository:
        pass

    class FakeRepositoryContext:
        def __enter__(self) -> FakeRepository:
            return FakeRepository()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_index_pages(**kwargs) -> IndexResult:
        calls.append(kwargs)
        return IndexResult(indexed_chunks=3, indexed_pages=2)

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr(
        "peoplebooks_mcp.cli.PeopleBooksRepository.connect",
        lambda database_url: FakeRepositoryContext(),
    )
    monkeypatch.setattr("peoplebooks_mcp.cli.index_pages", fake_index_pages)

    result = CliRunner().invoke(app, ["index"])

    assert result.exit_code == 0
    assert "Indexed 3 chunks across 2 pages." in result.output
    assert calls[0]["version_code"] == "pt862"


def test_serve_mcp_command_runs_stdio_server(monkeypatch) -> None:
    calls = []

    class FakeServer:
        def run(self) -> None:
            calls.append("run")

    def fake_create_server(*, database_url: str, search_timeout_seconds: float) -> FakeServer:
        calls.append((database_url, search_timeout_seconds))
        return FakeServer()

    monkeypatch.setattr("peoplebooks_mcp.cli.load_config", _test_config)
    monkeypatch.setattr("peoplebooks_mcp.cli.create_server", fake_create_server)

    result = CliRunner().invoke(app, ["serve-mcp"])

    assert result.exit_code == 0
    assert calls == [("postgresql://example/peoplebooks", 10.0), "run"]


def _test_config() -> AppConfig:
    version = DocVersionSeed(
        code="pt862",
        label="PeopleTools 8.62",
        seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
    )
    book = BookSeed(
        code="tpcr",
        version="pt862",
        title="PeopleCode API Reference",
        seed_url=version.seed_url,
    )
    return AppConfig(
        settings=RuntimeSettings(database_url="postgresql://example/peoplebooks"),
        doc_versions={"pt862": version},
        books={"tpcr": book},
    )
