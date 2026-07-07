from typer.testing import CliRunner

from peoplebooks_mcp.cli import app
from peoplebooks_mcp.config import AppConfig, BookSeed, DocVersionSeed, RuntimeSettings
from peoplebooks_mcp.repositories import StatusCounts
from peoplebooks_mcp.scraper.discovery import DiscoveryResult
from peoplebooks_mcp.scraper.scrape import ReparseResult, ScrapeResult


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
    assert "discovered: 4" in result.output
    assert "queued: 1" in result.output
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
