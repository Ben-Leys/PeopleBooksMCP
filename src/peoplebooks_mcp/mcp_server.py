from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from psycopg.errors import UndefinedColumn
from pydantic import BaseModel, ConfigDict, Field

from peoplebooks_mcp.config import load_config
from peoplebooks_mcp.repositories import (
    EXPECTED_SCHEMA_REVISION,
    BookRecord,
    ChunkRecord,
    DocVersionRecord,
    PageRecord,
    PageSearchRecord,
    PeopleBooksRepository,
    SearchResultRecord,
    SectionRecord,
)

JsonObject = dict[str, Any]
DetailLevel = Literal["compact", "normal", "full"]
SearchMode = Literal["auto", "exact"]

DEFAULT_VERSION = "pt862"
JSON_MIME_TYPE = "application/json"
DEFAULT_SNIPPET_CHARS = 450
DEFAULT_SECTION_CHARS = 1200
MAX_RESPONSE_CHARS = 8000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetailPayload(StrictModel):
    code: str
    message: str
    details: JsonObject | None = None
    page_id: int | None = Field(default=None, exclude_if=lambda value: value is None)
    path: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ErrorPayload(StrictModel):
    error: ErrorDetailPayload


class VersionPayload(StrictModel):
    code: str
    label: str


class BookPayload(StrictModel):
    id: int
    code: str
    title: str


class SearchBookPayload(StrictModel):
    code: str
    title: str


class PagePayload(StrictModel):
    id: int
    title: str | None = None
    normalized_path: str
    source_url: str


class SearchPagePayload(StrictModel):
    page_id: int
    title: str | None = None
    source_url: str


class PageSearchPayload(StrictModel):
    page_id: int
    book: SearchBookPayload
    title: str | None = None
    normalized_path: str
    source_url: str
    matched_terms: int
    score: float


class SectionOutlinePayload(StrictModel):
    id: int
    stable_id: str
    heading: str
    level: int


class SectionPayload(SectionOutlinePayload):
    page_id: int
    section_path: list[str]
    ordinal: int
    content: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ChunkPayload(StrictModel):
    id: int
    stable_id: str
    ordinal: int
    snippet: str | None = Field(default=None, exclude_if=lambda value: value is None)
    content: str | None = Field(default=None, exclude_if=lambda value: value is None)


class BudgetPayload(StrictModel):
    truncated: bool


class SearchSectionPayload(StrictModel):
    section_id: int
    stable_id: str
    heading: str
    section_path: list[str]


class SearchChunkPayload(StrictModel):
    snippet: str


class SearchResultPayload(StrictModel):
    book: SearchBookPayload
    page: SearchPagePayload
    section: SearchSectionPayload
    chunk: SearchChunkPayload


class SearchDocsResponse(StrictModel):
    match_mode: str
    budget: BudgetPayload
    version: VersionPayload
    results: list[SearchResultPayload]
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


class FindPagesResponse(StrictModel):
    query: str
    book_code: str | None
    version: VersionPayload
    pages: list[PageSearchPayload]


class PageDetailResponse(StrictModel):
    version: VersionPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    book: BookPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    page: PagePayload | None = Field(default=None, exclude_if=lambda value: value is None)
    section_count: int | None = Field(default=None, exclude_if=lambda value: value is None)
    returned_count: int | None = Field(default=None, exclude_if=lambda value: value is None)
    offset: int | None = Field(default=None, exclude_if=lambda value: value is None)
    next_offset: int | None = None
    sections: list[SectionOutlinePayload] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    suggestions: list[PageSearchPayload] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


class SectionDetailResponse(StrictModel):
    version: VersionPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    book: BookPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    page: PagePayload | None = Field(default=None, exclude_if=lambda value: value is None)
    section: SectionPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    chunks: list[ChunkPayload] | None = Field(default=None, exclude_if=lambda value: value is None)
    budget: BudgetPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


class ListBooksResponse(StrictModel):
    version: VersionPayload
    books: list[BookPayload]


def _structured_result(payload: JsonObject) -> CallToolResult:
    return CallToolResult(content=[], structuredContent=payload)


def create_server(*, database_url: str | None = None) -> FastMCP:
    resolved_database_url = database_url or load_config().settings.database_url
    server = FastMCP(
        "peoplebooks-mcp",
        instructions=(
            "Read-only Oracle PeopleBooks documentation server backed by local PostgreSQL. "
            "Handlers search and read indexed database content only."
        ),
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def search_docs(
        query: str,
        version: str = DEFAULT_VERSION,
        limit: int = 10,
        book_code: str | None = None,
        page_id: int | None = None,
        search_mode: SearchMode = "auto",
        max_chars: int = DEFAULT_SNIPPET_CHARS,
    ) -> Annotated[CallToolResult, SearchDocsResponse]:
        """Use first for questions or code checks. Returns compact snippets and stable handles."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            bounded_limit = _bounded_limit(limit)
            bounded_max_chars = _bounded_max_chars(max_chars, default=DEFAULT_SNIPPET_CHARS)
            try:
                if search_mode == "exact":
                    results = repository.search_chunks_exact(
                        doc_version_id=doc_version.id,
                        query=query,
                        limit=bounded_limit,
                        book_code=book_code,
                        page_id=page_id,
                    )
                    match_mode = "exact" if results else "none"
                else:
                    results = repository.search_chunks(
                        doc_version_id=doc_version.id,
                        query=query,
                        limit=bounded_limit,
                        book_code=book_code,
                        page_id=page_id,
                    )
                    match_mode = "strict"
            except UndefinedColumn:
                return _structured_result(
                    {
                        "match_mode": "error",
                        "budget": {
                            "truncated": False,
                        },
                        "version": _doc_version_payload(doc_version),
                        "results": [],
                        "error": {
                            "code": "schema_not_ready",
                            "message": (
                                "Full-text search is unavailable because chunks.search_vector is "
                                "missing. Run Alembic migrations and re-index the corpus."
                            ),
                            "details": {"expected_revision": EXPECTED_SCHEMA_REVISION},
                        },
                    }
                )
            if search_mode == "auto" and not results:
                results = repository.search_chunks_relaxed(
                    doc_version_id=doc_version.id,
                    query=query,
                    limit=bounded_limit,
                    book_code=book_code,
                    page_id=page_id,
                )
                match_mode = "relaxed" if results else "none"
        payloads, truncated = _search_result_payloads(
            results,
            max_chars=bounded_max_chars,
        )
        return _structured_result(
            {
                "match_mode": match_mode,
                "budget": {
                    "truncated": truncated,
                },
                "version": _doc_version_payload(doc_version),
                "results": payloads,
            }
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def find_pages(
        query: str,
        version: str = DEFAULT_VERSION,
        book_code: str | None = None,
        limit: int = 10,
    ) -> Annotated[CallToolResult, FindPagesResponse]:
        """Use to locate likely pages without spending tokens on section or chunk content."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            pages = repository.find_pages(
                doc_version_id=doc_version.id,
                query=query,
                book_code=book_code,
                limit=_bounded_limit(limit),
            )
        return _structured_result(
            {
                "query": query,
                "book_code": book_code,
                "version": _doc_version_payload(doc_version),
                "pages": [_page_search_payload(page) for page in pages],
            }
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def get_page(
        version: str = DEFAULT_VERSION,
        page_id: int | None = None,
        normalized_path: str | None = None,
        limit: int = 50,
        offset: int = 0,
        max_level: int | None = None,
    ) -> Annotated[CallToolResult, PageDetailResponse]:
        """Use after find_pages/search_docs to read compact, paged headings for one page."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            page = _resolve_page_or_none(
                repository,
                doc_version=doc_version,
                page_id=page_id,
                normalized_path=normalized_path,
            )
            if page is None:
                return _structured_result(
                    _page_not_found_payload(
                        repository,
                        doc_version=doc_version,
                        page_id=page_id,
                        normalized_path=normalized_path,
                    )
                )
            return _structured_result(
                _page_detail_payload(
                    repository,
                    page,
                    limit=limit,
                    offset=offset,
                    max_level=max_level,
                )
            )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def get_page_outline(
        version: str = DEFAULT_VERSION,
        page_id: int | None = None,
        normalized_path: str | None = None,
        limit: int = 50,
        offset: int = 0,
        max_level: int | None = None,
    ) -> Annotated[CallToolResult, PageDetailResponse]:
        """Use before get_section when only headings and section ids are needed."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            page = _resolve_page_or_none(
                repository,
                doc_version=doc_version,
                page_id=page_id,
                normalized_path=normalized_path,
            )
            if page is None:
                return _structured_result(
                    _page_not_found_payload(
                        repository,
                        doc_version=doc_version,
                        page_id=page_id,
                        normalized_path=normalized_path,
                    )
                )
            return _structured_result(
                _page_outline_payload(
                    repository,
                    page,
                    limit=limit,
                    offset=offset,
                    max_level=max_level,
                )
            )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def get_section(
        version: str = DEFAULT_VERSION,
        section_id: int | None = None,
        section_stable_id: str | None = None,
        page_id: int | None = None,
        normalized_path: str | None = None,
        detail: DetailLevel = "compact",
        max_chars: int = DEFAULT_SECTION_CHARS,
    ) -> Annotated[CallToolResult, SectionDetailResponse]:
        """Use after search_docs or get_page_outline. Compact by default; full content is opt-in."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            try:
                section = _resolve_section(
                    repository,
                    doc_version=doc_version,
                    section_id=section_id,
                    section_stable_id=section_stable_id,
                    page_id=page_id,
                    normalized_path=normalized_path,
                )
            except ValueError as error:
                return _structured_result(
                    _error_payload(code="section_not_found", message=str(error))
                )
            return _structured_result(
                _section_detail_payload(
                    repository,
                    section,
                    detail=detail,
                    max_chars=max_chars,
                )
            )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def list_books(version: str = DEFAULT_VERSION) -> Annotated[CallToolResult, ListBooksResponse]:
        """List book codes for scoping later search_docs or find_pages calls."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            books = repository.list_books(doc_version_id=doc_version.id)
        return _structured_result(
            {
                "version": _doc_version_payload(doc_version),
                "books": [_book_payload(book) for book in books],
            }
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def health(version: str = DEFAULT_VERSION) -> Annotated[CallToolResult, JsonObject]:
        """Report schema and index readiness for agent querying."""
        try:
            with PeopleBooksRepository.connect(resolved_database_url) as repository:
                schema_revision = repository.get_schema_revision()
                missing_columns = repository.list_missing_required_columns()
                schema_is_current = schema_revision == EXPECTED_SCHEMA_REVISION
                doc_version = repository.get_doc_version_by_code(version)
                content = None
                if doc_version is not None:
                    content_record = repository.get_content_health(
                        doc_version_id=doc_version.id,
                        include_index_counts=not missing_columns,
                    )
                    content = _content_health_payload(content_record)
                status = _health_status(
                    schema_is_current=schema_is_current,
                    missing_columns=missing_columns,
                    content=content,
                    doc_version_found=doc_version is not None,
                )
        except Exception as error:
            return _structured_result(
                {
                    "status": "unavailable",
                    "error": {
                        "code": "database_unavailable",
                        "message": str(error),
                    },
                }
            )

        return _structured_result(
            {
                "status": status,
                "schema": {
                    "current_revision": schema_revision,
                    "expected_revision": EXPECTED_SCHEMA_REVISION,
                    "is_current": schema_is_current,
                    "missing_required_columns": missing_columns,
                },
                "version": _doc_version_payload(doc_version) if doc_version is not None else None,
                "content": content,
            }
        )

    @server.resource(
        "peoplebooks://versions",
        name="peoplebooks_versions",
        title="PeopleBooks Versions",
        description="List discovered PeopleBooks documentation versions.",
        mime_type=JSON_MIME_TYPE,
    )
    def versions_resource() -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            versions = repository.list_doc_versions()
        return _json({"versions": [_doc_version_payload(version) for version in versions]})

    @server.resource(
        "peoplebooks://versions/{version_code}",
        name="peoplebooks_version",
        title="PeopleBooks Version",
        description="Read one discovered PeopleBooks documentation version.",
        mime_type=JSON_MIME_TYPE,
    )
    def version_resource(version_code: str) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            version = _require_doc_version(repository, version_code)
            books = repository.list_books(doc_version_id=version.id)
        return _json(
            {
                "version": _doc_version_payload(version),
                "books": [_book_payload(book) for book in books],
            }
        )

    @server.resource(
        "peoplebooks://versions/{version_code}/books",
        name="peoplebooks_books",
        title="PeopleBooks Books",
        description="List discovered books for a PeopleBooks version.",
        mime_type=JSON_MIME_TYPE,
    )
    def books_resource(version_code: str) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            version = _require_doc_version(repository, version_code)
            books = repository.list_books(doc_version_id=version.id)
        return _json(
            {
                "version": _doc_version_payload(version),
                "books": [_book_payload(book) for book in books],
            }
        )

    @server.resource(
        "peoplebooks://versions/{version_code}/books/{book_code}/pages",
        name="peoplebooks_pages",
        title="PeopleBooks Pages",
        description="List discovered pages for a PeopleBooks book.",
        mime_type=JSON_MIME_TYPE,
    )
    def pages_resource(version_code: str, book_code: str) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            version = _require_doc_version(repository, version_code)
            book = _require_book(repository, doc_version_id=version.id, code=book_code)
            pages = repository.list_pages_for_book(doc_version_id=version.id, book_id=book.id)
        return _json(
            {
                "version": _doc_version_payload(version),
                "book": _book_payload(book),
                "pages": [_page_payload(page) for page in pages],
            }
        )

    @server.resource(
        "peoplebooks://pages/{page_id}",
        name="peoplebooks_page",
        title="PeopleBooks Page",
        description="Read one parsed PeopleBooks page.",
        mime_type=JSON_MIME_TYPE,
    )
    def page_resource(page_id: int) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            page = _require_page_by_id(repository, page_id)
            return _json(
                _page_detail_payload(
                    repository,
                    page,
                    limit=50,
                    offset=0,
                    max_level=None,
                )
            )

    @server.resource(
        "peoplebooks://sections/{section_id}",
        name="peoplebooks_section",
        title="PeopleBooks Section",
        description="Read one parsed PeopleBooks section.",
        mime_type=JSON_MIME_TYPE,
    )
    def section_resource(section_id: int) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            section = _require_section_by_id(repository, section_id)
            return _json(
                _section_detail_payload(
                    repository,
                    section,
                    detail="compact",
                    max_chars=DEFAULT_SECTION_CHARS,
                )
            )

    return server


def _require_doc_version(
    repository: PeopleBooksRepository,
    code: str,
) -> DocVersionRecord:
    doc_version = repository.get_doc_version_by_code(code)
    if doc_version is None:
        raise ValueError(f"Unknown documentation version: {code!r}")
    return doc_version


def _require_doc_version_by_id(
    repository: PeopleBooksRepository,
    doc_version_id: int,
) -> DocVersionRecord:
    doc_version = repository.get_doc_version_by_id(doc_version_id)
    if doc_version is None:
        raise ValueError(f"Unknown documentation version id: {doc_version_id}")
    return doc_version


def _require_book(
    repository: PeopleBooksRepository,
    *,
    doc_version_id: int,
    code: str,
) -> BookRecord:
    book = repository.get_book_by_code(doc_version_id=doc_version_id, code=code)
    if book is None:
        raise ValueError(f"Unknown book {code!r} for documentation version id {doc_version_id}")
    return book


def _require_book_by_id(repository: PeopleBooksRepository, book_id: int) -> BookRecord:
    book = repository.get_book_by_id(book_id)
    if book is None:
        raise ValueError(f"Unknown book id: {book_id}")
    return book


def _require_page_by_id(repository: PeopleBooksRepository, page_id: int) -> PageRecord:
    page = repository.get_page_by_id(page_id)
    if page is None:
        raise ValueError(f"Unknown page id: {page_id}")
    return page


def _require_section_by_id(
    repository: PeopleBooksRepository,
    section_id: int,
) -> SectionRecord:
    section = repository.get_section_by_id(section_id)
    if section is None:
        raise ValueError(f"Unknown section id: {section_id}")
    return section


def _resolve_page(
    repository: PeopleBooksRepository,
    *,
    doc_version: DocVersionRecord,
    page_id: int | None,
    normalized_path: str | None,
) -> PageRecord:
    if page_id is not None:
        page = _require_page_by_id(repository, page_id)
        _ensure_page_version(page, doc_version)
        return page

    if normalized_path:
        page = repository.get_page_by_normalized_path(
            doc_version_id=doc_version.id,
            normalized_path=normalized_path,
        )
        if page is not None:
            return page
        raise ValueError(
            f"Unknown page path {normalized_path!r} for documentation version {doc_version.code!r}"
        )

    raise ValueError("Provide either page_id or normalized_path")


def _resolve_page_or_none(
    repository: PeopleBooksRepository,
    *,
    doc_version: DocVersionRecord,
    page_id: int | None,
    normalized_path: str | None,
) -> PageRecord | None:
    if page_id is not None:
        page = repository.get_page_by_id(page_id)
        if page is None or page.doc_version_id != doc_version.id:
            return None
        return page

    if normalized_path:
        return repository.get_page_by_normalized_path(
            doc_version_id=doc_version.id,
            normalized_path=normalized_path,
        )

    return None


def _resolve_section(
    repository: PeopleBooksRepository,
    *,
    doc_version: DocVersionRecord,
    section_id: int | None,
    section_stable_id: str | None,
    page_id: int | None,
    normalized_path: str | None,
) -> SectionRecord:
    if section_id is not None:
        section = _require_section_by_id(repository, section_id)
        page = _require_page_by_id(repository, section.page_id)
        _ensure_page_version(page, doc_version)
        return section

    if not section_stable_id:
        raise ValueError("Provide either section_id or section_stable_id")

    page = _resolve_page(
        repository,
        doc_version=doc_version,
        page_id=page_id,
        normalized_path=normalized_path,
    )
    section = repository.get_section_by_stable_id(
        page_id=page.id,
        stable_id=section_stable_id,
    )
    if section is None:
        raise ValueError(f"Unknown section stable id {section_stable_id!r} for page {page.id}")
    return section


def _ensure_page_version(page: PageRecord, doc_version: DocVersionRecord) -> None:
    if page.doc_version_id != doc_version.id:
        raise ValueError(f"Page {page.id} is not in documentation version {doc_version.code!r}")


def _page_detail_payload(
    repository: PeopleBooksRepository,
    page: PageRecord,
    *,
    limit: int,
    offset: int,
    max_level: int | None,
) -> JsonObject:
    version = _require_doc_version_by_id(repository, page.doc_version_id)
    book = _require_book_by_id(repository, page.book_id)
    sections = repository.list_sections_for_page(page_id=page.id)
    section_count, bounded_offset, next_offset, window = _windowed_sections(
        sections,
        limit=limit,
        offset=offset,
        max_level=max_level,
    )

    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "page": _page_payload(page),
        "section_count": section_count,
        "returned_count": len(window),
        "offset": bounded_offset,
        "next_offset": next_offset,
        "sections": [_section_outline_payload(section) for section in window],
    }


def _page_outline_payload(
    repository: PeopleBooksRepository,
    page: PageRecord,
    *,
    limit: int,
    offset: int,
    max_level: int | None,
) -> JsonObject:
    version = _require_doc_version_by_id(repository, page.doc_version_id)
    book = _require_book_by_id(repository, page.book_id)
    sections = repository.list_sections_for_page(page_id=page.id)
    section_count, bounded_offset, next_offset, window = _windowed_sections(
        sections,
        limit=limit,
        offset=offset,
        max_level=max_level,
    )

    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "page": _page_payload(page),
        "section_count": section_count,
        "returned_count": len(window),
        "offset": bounded_offset,
        "next_offset": next_offset,
        "sections": [_section_outline_payload(section) for section in window],
    }


def _windowed_sections(
    sections: Sequence[SectionRecord],
    *,
    limit: int,
    offset: int,
    max_level: int | None,
) -> tuple[int, int, int | None, Sequence[SectionRecord]]:
    if max_level is not None:
        sections = [section for section in sections if section.level <= max(1, max_level)]
    section_count = len(sections)
    bounded_offset = _bounded_offset(offset)
    bounded_limit = _bounded_outline_limit(limit)
    window = sections[bounded_offset : bounded_offset + bounded_limit]
    next_offset = bounded_offset + bounded_limit
    if next_offset >= section_count:
        next_offset = None
    return section_count, bounded_offset, next_offset, window


def _section_detail_payload(
    repository: PeopleBooksRepository,
    section: SectionRecord,
    *,
    detail: DetailLevel,
    max_chars: int,
) -> JsonObject:
    page = _require_page_by_id(repository, section.page_id)
    version = _require_doc_version_by_id(repository, page.doc_version_id)
    book = _require_book_by_id(repository, page.book_id)
    chunks = repository.list_chunks_for_section(section_id=section.id)
    bounded_max_chars = _bounded_max_chars(max_chars, default=DEFAULT_SECTION_CHARS)
    section_texts = [section.content] if detail == "full" else []
    chunk_texts = [chunk.content for chunk in chunks]
    budgeted_texts, text_truncated = _truncate_texts_to_budget(
        [*section_texts, *chunk_texts],
        max_chars=bounded_max_chars,
    )
    section_content = budgeted_texts[0] if section_texts else None
    chunk_start = 1 if section_texts else 0
    chunk_contents = budgeted_texts[chunk_start:]
    chunk_payloads, chunk_truncated = _chunk_payloads(
        chunks,
        detail=detail,
        contents=chunk_contents,
    )
    section_payload = _section_payload(
        section,
        content=section_content,
    )

    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "page": _page_payload(page),
        "section": section_payload,
        "chunks": chunk_payloads,
        "budget": {
            "truncated": text_truncated or chunk_truncated,
        },
    }


def _doc_version_payload(version: DocVersionRecord) -> JsonObject:
    return {
        "code": version.code,
        "label": version.label,
    }


def _book_payload(book: BookRecord) -> JsonObject:
    return {
        "id": book.id,
        "code": book.code,
        "title": book.title,
    }


def _page_payload(page: PageRecord) -> JsonObject:
    return {
        "id": page.id,
        "title": page.title,
        "normalized_path": page.normalized_path,
        "source_url": page.source_url,
    }


def _page_search_payload(page: PageSearchRecord) -> JsonObject:
    return {
        "page_id": page.id,
        "book": {
            "code": page.book_code,
            "title": page.book_title,
        },
        "title": page.title,
        "normalized_path": page.normalized_path,
        "source_url": page.source_url,
        "matched_terms": page.matched_terms,
        "score": page.score,
    }


def _section_payload(
    section: SectionRecord,
    *,
    content: str | None,
) -> JsonObject:
    payload = {
        "id": section.id,
        "page_id": section.page_id,
        "stable_id": section.stable_id,
        "heading": section.heading,
        "level": section.level,
        "section_path": section.section_path,
        "ordinal": section.ordinal,
    }
    if content is not None:
        payload["content"] = content
    return payload


def _section_outline_payload(section: SectionRecord) -> JsonObject:
    return {
        "id": section.id,
        "stable_id": section.stable_id,
        "heading": section.heading,
        "level": section.level,
    }


def _chunk_payloads(
    chunks: Sequence[ChunkRecord],
    *,
    detail: DetailLevel,
    contents: Sequence[str],
) -> tuple[list[JsonObject], bool]:
    payloads: list[JsonObject] = []
    truncated_any = len(contents) < len(chunks)
    for chunk, text in zip(chunks, contents, strict=False):
        payload: JsonObject = {
            "id": chunk.id,
            "stable_id": chunk.stable_id,
            "ordinal": chunk.ordinal,
        }
        if detail == "full":
            payload["content"] = text
        else:
            payload["snippet"] = text
        payloads.append(payload)
    return payloads, truncated_any


def _search_result_payload(result: SearchResultRecord) -> JsonObject:
    return {
        "book": {
            "code": result.book_code,
            "title": result.book_title,
        },
        "page": {
            "page_id": result.page_id,
            "title": result.page_title,
            "source_url": result.source_url,
        },
        "section": {
            "section_id": result.section_id,
            "stable_id": result.section_stable_id,
            "heading": result.section_heading,
            "section_path": result.section_path,
        },
        "chunk": {
            "snippet": result.snippet,
        },
    }


def _search_result_payloads(
    results: Sequence[SearchResultRecord],
    *,
    max_chars: int,
) -> tuple[list[JsonObject], bool]:
    payloads: list[JsonObject] = []
    snippets, truncated_any = _truncate_texts_to_budget(
        [_strip_search_markup(result.snippet) for result in results],
        max_chars=max_chars,
    )
    for result, snippet in zip(results, snippets, strict=False):
        payload = _search_result_payload(result)
        payload["chunk"]["snippet"] = snippet
        payloads.append(payload)
    return payloads, truncated_any


def _strip_search_markup(text: str) -> str:
    return text.replace("<mark>", "").replace("</mark>", "")


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _bounded_max_chars(max_chars: int, *, default: int) -> int:
    if max_chars < 1:
        return default
    return max(40, min(max_chars, MAX_RESPONSE_CHARS))


def _bounded_outline_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _bounded_offset(offset: int) -> int:
    return max(0, offset)


def _truncate_texts_to_budget(texts: Sequence[str], *, max_chars: int) -> tuple[list[str], bool]:
    if not texts:
        return [], False

    remaining = max(0, max_chars)
    output: list[str] = []
    truncated_any = False
    for index, text in enumerate(texts):
        slots_left = len(texts) - index
        limit = remaining // slots_left if slots_left else 0
        truncated_text, truncated = _truncate_text(text, max_chars=limit)
        output.append(truncated_text)
        remaining -= len(truncated_text)
        truncated_any = truncated_any or truncated

    return output, truncated_any


def _truncate_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    clean = " ".join(text.split())
    if max_chars <= 0:
        return "", bool(clean)
    if len(clean) <= max_chars:
        return clean, False
    if max_chars <= 3:
        return clean[:max_chars], True
    if clean.startswith("..."):
        return "..." + clean[-(max_chars - 3) :].lstrip(), True
    return clean[: max_chars - 3].rstrip() + "...", True


def _page_not_found_payload(
    repository: PeopleBooksRepository,
    *,
    doc_version: DocVersionRecord,
    page_id: int | None,
    normalized_path: str | None,
) -> JsonObject:
    if page_id is None and not normalized_path:
        return _error_payload(
            code="invalid_request",
            message=(
                "Provide either page_id returned by search/find_pages or an exact "
                "normalized_path."
            ),
        )

    suggestions = []
    if normalized_path:
        suggestions = repository.suggest_pages_for_path(
            doc_version_id=doc_version.id,
            normalized_path=normalized_path,
            limit=5,
        )

    return {
        "error": {
            "code": "page_not_found",
            "message": "No page matched the supplied identifier.",
            "page_id": page_id,
            "path": normalized_path,
        },
        "version": _doc_version_payload(doc_version),
        "suggestions": [_page_search_payload(page) for page in suggestions],
    }


def _error_payload(
    *,
    code: str,
    message: str,
    details: JsonObject | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


def _content_health_payload(content: Any) -> JsonObject:
    partial_index = (
        content.total_chunks != content.indexed_chunks
        or content.parsed_pages != content.indexed_pages
    )
    return {
        "total_pages": content.total_pages,
        "parsed_pages": content.parsed_pages,
        "indexed_pages": content.indexed_pages,
        "total_chunks": content.total_chunks,
        "indexed_chunks": content.indexed_chunks,
        "partial_index": partial_index,
    }


def _health_status(
    *,
    schema_is_current: bool,
    missing_columns: Sequence[str],
    content: JsonObject | None,
    doc_version_found: bool,
) -> str:
    if not schema_is_current or missing_columns or not doc_version_found:
        return "degraded"
    if content is None or content["parsed_pages"] == 0 or content["indexed_chunks"] == 0:
        return "degraded"
    if content["partial_index"]:
        return "degraded"
    return "ready"


def _json(payload: JsonObject) -> str:
    return json.dumps(payload, sort_keys=True)
