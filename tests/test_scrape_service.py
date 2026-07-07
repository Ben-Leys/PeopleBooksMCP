from __future__ import annotations

from dataclasses import dataclass

import pytest

from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.fetcher import FetchError, FetchResult, sha256_content_hash
from peoplebooks_mcp.scraper.scrape import ScrapeProgress, reparse_pages, scrape_pages


@dataclass(frozen=True, slots=True)
class SimpleVersion:
    id: int


@dataclass(frozen=True, slots=True)
class SimplePage:
    id: int
    raw_html: str
    source_url: str
    normalized_path: str
    fetch_status: str


@dataclass(slots=True)
class FakeFetcher:
    responses: dict[str, str | FetchError]
    calls: list[str]

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, FetchError):
            raise response
        return FetchResult(
            url=url,
            final_url=url,
            text=response,
            status_code=200,
            elapsed_ms=7,
            attempts=1,
            content_hash=sha256_content_hash(response),
            source_metadata={"content_type": "text/html"},
        )


@dataclass(slots=True)
class FailingFetcher:
    calls: list[str]

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        raise AssertionError("fetched raw HTML should be parsed without network")


@dataclass(slots=True)
class FakeRepository:
    page: SimplePage
    sections: list

    def get_doc_version_by_code(self, code: str) -> SimpleVersion:
        return SimpleVersion(id=1)

    def list_next_queued_pages(self, *, doc_version_id: int, limit: int) -> list[SimplePage]:
        return []

    def list_next_scrape_pages(self, *, doc_version_id: int, limit: int) -> list[SimplePage]:
        return [self.page]

    def replace_page_sections(self, *, page_id: int, parser_version: str, sections: list) -> None:
        self.sections = sections


def test_scrape_pages_parses_already_fetched_raw_html_without_fetching() -> None:
    page = SimplePage(
        id=10,
        raw_html=_leaf_html("Fetched Before Crash"),
        source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page.html",
        normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page.html",
        fetch_status="fetched",
    )
    repository = FakeRepository(page=page, sections=[])
    fetcher = FailingFetcher(calls=[])

    result = scrape_pages(
        repository=repository,
        version_code="pt862",
        fetcher=fetcher,
        limit=1,
        parser_version="parser-v1",
    )

    assert result.scraped == 0
    assert result.failed == 0
    assert result.parsed == 1
    assert fetcher.calls == []
    assert repository.sections[0].heading == "Fetched Before Crash"


def test_scrape_pages_reports_progress_for_pages_as_they_are_processed() -> None:
    page = SimplePage(
        id=10,
        raw_html=_leaf_html("Fetched Before Crash"),
        source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page.html",
        normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page.html",
        fetch_status="fetched",
    )
    repository = FakeRepository(page=page, sections=[])
    fetcher = FailingFetcher(calls=[])
    progress_events: list[ScrapeProgress] = []

    scrape_pages(
        repository=repository,
        version_code="pt862",
        fetcher=fetcher,
        limit=1,
        parser_version="parser-v1",
        progress=progress_events.append,
    )

    assert [
        (event.pages_processed, event.total_pages, event.scraped, event.failed, event.parsed)
        for event in progress_events
    ] == [
        (0, 1, 0, 0, 0),
        (1, 1, 0, 0, 1),
    ]


def test_scrape_pages_obeys_limit_and_resumes_from_remaining_queue(postgres_url: str) -> None:
    run_migrations(postgres_url)
    with PeopleBooksRepository.connect(postgres_url) as repository:
        version_id, page_urls = _seed_pages(repository, count=3)
        fetcher = FakeFetcher(
            responses={url: _leaf_html(f"Page {index}") for index, url in enumerate(page_urls)},
            calls=[],
        )

        first_result = scrape_pages(
            repository=repository,
            version_code="pt862",
            fetcher=fetcher,
            limit=2,
            parser_version="parser-v1",
        )
        second_result = scrape_pages(
            repository=repository,
            version_code="pt862",
            fetcher=fetcher,
            limit=2,
            parser_version="parser-v1",
        )

        counts = repository.get_status_counts(doc_version_id=version_id)

    assert first_result.scraped == 2
    assert first_result.parsed == 2
    assert second_result.scraped == 1
    assert counts.queued == 0
    assert counts.parsed == 3
    assert fetcher.calls == page_urls


def test_scrape_pages_resumes_fetched_unparsed_pages_without_refetching(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    with PeopleBooksRepository.connect(postgres_url) as repository:
        version_id, page_urls = _seed_pages(repository, count=1)
        page = repository.list_next_queued_pages(doc_version_id=version_id, limit=1)[0]
        raw_html = _leaf_html("Fetched Before Crash")
        repository.record_fetch_success(
            page_id=page.id,
            raw_html=raw_html,
            content_hash=sha256_content_hash(raw_html),
            status_code=200,
            elapsed_ms=5,
            source_url=page_urls[0],
        )
        fetcher = FailingFetcher(calls=[])

        result = scrape_pages(
            repository=repository,
            version_code="pt862",
            fetcher=fetcher,
            limit=1,
            parser_version="parser-v1",
        )
        counts = repository.get_status_counts(doc_version_id=version_id)
        sections = repository.list_sections_for_page(page_id=page.id)

    assert result.scraped == 0
    assert result.failed == 0
    assert result.parsed == 1
    assert counts.fetched == 0
    assert counts.parsed == 1
    assert fetcher.calls == []
    assert sections[0].heading == "Fetched Before Crash"


def test_scrape_pages_records_failed_fetch_and_continues(postgres_url: str) -> None:
    run_migrations(postgres_url)
    with PeopleBooksRepository.connect(postgres_url) as repository:
        version_id, page_urls = _seed_pages(repository, count=2)
        fetcher = FakeFetcher(
            responses={
                page_urls[0]: FetchError(
                    "HTTP 503 while fetching page",
                    attempts=2,
                    status_code=503,
                    elapsed_ms=13,
                ),
                page_urls[1]: _leaf_html("Successful Page"),
            },
            calls=[],
        )

        result = scrape_pages(
            repository=repository,
            version_code="pt862",
            fetcher=fetcher,
            limit=10,
            parser_version="parser-v1",
        )
        counts = repository.get_status_counts(doc_version_id=version_id)
        rows = repository.connection.execute(
            "SELECT id, fetch_status FROM pages ORDER BY normalized_path"
        ).fetchall()
        failed_events = repository.list_fetch_events(page_id=rows[0]["id"])
        success_events = repository.list_fetch_events(page_id=rows[1]["id"])

    assert result.scraped == 1
    assert result.failed == 1
    assert result.parsed == 1
    assert counts.failed == 1
    assert counts.parsed == 1
    assert [row["fetch_status"] for row in rows] == ["failed", "parsed"]
    assert failed_events[0].fetch_status == "failed"
    assert failed_events[0].status_code == 503
    assert success_events[0].fetch_status == "fetched"


def test_reparse_pages_rebuilds_sections_from_raw_html_without_fetching(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    with PeopleBooksRepository.connect(postgres_url) as repository:
        version_id, page_urls = _seed_pages(repository, count=1)
        page = repository.list_next_queued_pages(doc_version_id=version_id, limit=1)[0]
        raw_html = _leaf_html("Fresh Heading", body="Fresh parsed body.")
        repository.record_fetch_success(
            page_id=page.id,
            raw_html=raw_html,
            content_hash=sha256_content_hash(raw_html),
            status_code=200,
            elapsed_ms=5,
            source_url=page_urls[0],
        )
        repository.replace_page_sections(
            page_id=page.id,
            parser_version="parser-v1",
            sections=[],
        )

        result = reparse_pages(
            repository=repository,
            version_code="pt862",
            parser_version="parser-v2",
        )
        sections = repository.list_sections_for_page(page_id=page.id)
        counts = repository.get_status_counts(doc_version_id=version_id)

    assert result.reparsed == 1
    assert counts.parsed == 1
    assert sections[0].heading == "Fresh Heading"
    assert sections[0].content == "Fresh parsed body."
    assert sections[0].parser_version == "parser-v2"


def test_reparse_pages_rejects_unknown_version(postgres_url: str) -> None:
    run_migrations(postgres_url)
    with PeopleBooksRepository.connect(postgres_url) as repository:
        with pytest.raises(ValueError, match="Unknown discovered version"):
            reparse_pages(
                repository=repository,
                version_code="pt999",
                parser_version="parser-v2",
            )


def _seed_pages(
    repository: PeopleBooksRepository,
    *,
    count: int,
) -> tuple[int, list[str]]:
    version = repository.upsert_doc_version(
        code="pt862",
        label="PeopleTools 8.62",
        seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
    )
    book = repository.upsert_book(
        doc_version_id=version.id,
        code="tpcr",
        title="PeopleCode API Reference",
        seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html",
    )
    page_urls = [
        f"https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page_{index}.html"
        for index in range(count)
    ]
    for index, url in enumerate(page_urls):
        repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url=url,
            normalized_path=f"/cd/G41075_01/pt862pbr3/eng/pt/tpcr/page_{index}.html",
            source_url=url,
            title=f"Page {index}",
        )
    return version.id, page_urls


def _leaf_html(heading: str, *, body: str | None = None) -> str:
    return f"""
    <html>
      <body>
        <main>
          <h1>{heading}</h1>
          <p>{body or f"{heading} body."}</p>
        </main>
      </body>
    </html>
    """
