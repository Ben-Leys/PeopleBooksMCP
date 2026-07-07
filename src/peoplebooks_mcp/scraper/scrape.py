from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from peoplebooks_mcp.parser.leaf import ParsedSection, parse_leaf_page
from peoplebooks_mcp.repositories import ChunkInput, PageRecord, PeopleBooksRepository, SectionInput
from peoplebooks_mcp.scraper.fetcher import FetchError, FetchResult
from peoplebooks_mcp.scraper.oracle import oracle_source_metadata

DEFAULT_PARSER_VERSION = "v1"


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult:
        pass


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    scraped: int
    failed: int
    parsed: int


@dataclass(frozen=True, slots=True)
class ScrapeProgress:
    pages_processed: int
    total_pages: int
    scraped: int
    failed: int
    parsed: int


@dataclass(frozen=True, slots=True)
class ReparseResult:
    reparsed: int


def scrape_pages(
    *,
    repository: PeopleBooksRepository,
    version_code: str,
    fetcher: Fetcher,
    limit: int,
    parser_version: str = DEFAULT_PARSER_VERSION,
    progress: Callable[[ScrapeProgress], None] | None = None,
) -> ScrapeResult:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    doc_version = repository.get_doc_version_by_code(version_code)
    if doc_version is None:
        raise ValueError(f"Unknown discovered version: {version_code!r}")

    scraped = 0
    failed = 0
    parsed = 0
    pages = repository.list_next_scrape_pages(doc_version_id=doc_version.id, limit=limit)
    total_pages = len(pages)
    _report_scrape_progress(
        progress=progress,
        pages_processed=0,
        total_pages=total_pages,
        scraped=scraped,
        failed=failed,
        parsed=parsed,
    )

    for pages_processed, page in enumerate(pages, start=1):
        if page.fetch_status == "fetched" and page.raw_html is not None:
            _replace_parsed_content(
                repository=repository,
                page=page,
                parser_version=parser_version,
            )
            parsed += 1
            _report_scrape_progress(
                progress=progress,
                pages_processed=pages_processed,
                total_pages=total_pages,
                scraped=scraped,
                failed=failed,
                parsed=parsed,
            )
            continue

        try:
            fetch_result = fetcher.fetch(page.source_url)
        except FetchError as error:
            failed += 1
            repository.record_fetch_failure(
                page_id=page.id,
                error_message=str(error),
                status_code=error.status_code,
                elapsed_ms=error.elapsed_ms,
                source_url=page.source_url,
                source_metadata=oracle_source_metadata(page.source_url),
                metadata={"attempts": error.attempts},
            )
            _report_scrape_progress(
                progress=progress,
                pages_processed=pages_processed,
                total_pages=total_pages,
                scraped=scraped,
                failed=failed,
                parsed=parsed,
            )
            continue

        fetched_page, _event = repository.record_fetch_success(
            page_id=page.id,
            raw_html=fetch_result.text,
            content_hash=fetch_result.content_hash,
            status_code=fetch_result.status_code,
            elapsed_ms=fetch_result.elapsed_ms,
            source_url=page.source_url,
            source_metadata=oracle_source_metadata(fetch_result.final_url)
            | fetch_result.source_metadata,
            metadata={"attempts": fetch_result.attempts},
        )
        _replace_parsed_content(
            repository=repository,
            page=fetched_page,
            parser_version=parser_version,
        )
        scraped += 1
        parsed += 1
        _report_scrape_progress(
            progress=progress,
            pages_processed=pages_processed,
            total_pages=total_pages,
            scraped=scraped,
            failed=failed,
            parsed=parsed,
        )

    return ScrapeResult(scraped=scraped, failed=failed, parsed=parsed)


def reparse_pages(
    *,
    repository: PeopleBooksRepository,
    version_code: str,
    parser_version: str,
) -> ReparseResult:
    doc_version = repository.get_doc_version_by_code(version_code)
    if doc_version is None:
        raise ValueError(f"Unknown discovered version: {version_code!r}")

    reparsed = 0
    for page in repository.list_pages_with_raw_html(doc_version_id=doc_version.id):
        _replace_parsed_content(
            repository=repository,
            page=page,
            parser_version=parser_version,
        )
        reparsed += 1

    return ReparseResult(reparsed=reparsed)


def _replace_parsed_content(
    *,
    repository: PeopleBooksRepository,
    page: PageRecord,
    parser_version: str,
) -> None:
    if page.raw_html is None:
        raise ValueError(f"Page {page.id} has no raw HTML to parse")

    sections = parse_leaf_page(page.raw_html, page_stable_id=_page_stable_id(page))
    repository.replace_page_sections(
        page_id=page.id,
        parser_version=parser_version,
        sections=[
            _section_input(
                section=section,
                page=page,
            )
            for section in sections
        ],
    )


def _report_scrape_progress(
    *,
    progress: Callable[[ScrapeProgress], None] | None,
    pages_processed: int,
    total_pages: int,
    scraped: int,
    failed: int,
    parsed: int,
) -> None:
    if progress is None:
        return
    progress(
        ScrapeProgress(
            pages_processed=pages_processed,
            total_pages=total_pages,
            scraped=scraped,
            failed=failed,
            parsed=parsed,
        )
    )


def _section_input(*, section: ParsedSection, page: PageRecord) -> SectionInput:
    return SectionInput(
        stable_id=section.stable_id,
        heading=section.heading,
        level=section.level,
        section_path=section.section_path,
        ordinal=section.ordinal,
        content=section.content,
        chunks=[
            ChunkInput(
                stable_id=chunk.stable_id,
                ordinal=chunk.ordinal,
                content=chunk.content,
                metadata=chunk.metadata
                | {
                    "source_url": page.source_url,
                    "normalized_path": page.normalized_path,
                },
            )
            for chunk in section.chunks
        ],
        source_metadata=section.source_metadata
        | {
            "source_url": page.source_url,
            "normalized_path": page.normalized_path,
        },
    )


def _page_stable_id(page: PageRecord) -> str:
    path = PurePosixPath(page.normalized_path)
    slug = re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")
    if not slug:
        slug = f"page_{page.id}"
    book_code = path.parent.name.lower()
    if book_code:
        return f"{book_code}/{slug}"
    return slug
