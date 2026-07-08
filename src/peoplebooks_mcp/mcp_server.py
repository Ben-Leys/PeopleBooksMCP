from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from psycopg.errors import UndefinedColumn

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

DEFAULT_VERSION = "pt862"
JSON_MIME_TYPE = "application/json"


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
    ) -> JsonObject:
        """Search indexed PeopleBooks chunks; returned page/section ids are preferred handles."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            try:
                results = repository.search_chunks(
                    doc_version_id=doc_version.id,
                    query=query,
                    limit=_bounded_limit(limit),
                    book_code=book_code,
                    page_id=page_id,
                )
            except UndefinedColumn:
                return _error_payload(
                    code="schema_not_ready",
                    message=(
                        "Full-text search is unavailable because chunks.search_vector is "
                        "missing. Run Alembic migrations and re-index the corpus."
                    ),
                    details={"expected_revision": EXPECTED_SCHEMA_REVISION},
                )
            match_mode = "strict"
            if not results:
                results = repository.search_chunks_relaxed(
                    doc_version_id=doc_version.id,
                    query=query,
                    limit=_bounded_limit(limit),
                    book_code=book_code,
                    page_id=page_id,
                )
                match_mode = "relaxed" if results else "none"
        return {
            "query": query,
            "match_mode": match_mode,
            "filters": {
                "book_code": book_code,
                "page_id": page_id,
            },
            "version": _doc_version_payload(doc_version),
            "results": [_search_result_payload(result) for result in results],
        }

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def find_pages(
        query: str,
        version: str = DEFAULT_VERSION,
        book_code: str | None = None,
        limit: int = 10,
    ) -> JsonObject:
        """Find likely pages without returning section or chunk content."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            pages = repository.find_pages(
                doc_version_id=doc_version.id,
                query=query,
                book_code=book_code,
                limit=_bounded_limit(limit),
            )
        return {
            "query": query,
            "book_code": book_code,
            "version": _doc_version_payload(doc_version),
            "pages": [_page_search_payload(page) for page in pages],
        }

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
    ) -> JsonObject:
        """Read compact page metadata and paged headings by page_id or normalized_path."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            page = _resolve_page_or_none(
                repository,
                doc_version=doc_version,
                page_id=page_id,
                normalized_path=normalized_path,
            )
            if page is None:
                return _page_not_found_payload(
                    repository,
                    doc_version=doc_version,
                    page_id=page_id,
                    normalized_path=normalized_path,
                )
            return _page_detail_payload(
                repository,
                page,
                limit=limit,
                offset=offset,
                max_level=max_level,
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
    ) -> JsonObject:
        """Read a compact, paged heading outline; use section ids for precise content."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            page = _resolve_page_or_none(
                repository,
                doc_version=doc_version,
                page_id=page_id,
                normalized_path=normalized_path,
            )
            if page is None:
                return _page_not_found_payload(
                    repository,
                    doc_version=doc_version,
                    page_id=page_id,
                    normalized_path=normalized_path,
                )
            return _page_outline_payload(
                repository,
                page,
                limit=limit,
                offset=offset,
                max_level=max_level,
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
    ) -> JsonObject:
        """Read a parsed section by id or by page plus stable section id."""
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
                return _error_payload(code="section_not_found", message=str(error))
            return _section_detail_payload(repository, section)

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def list_books(version: str = DEFAULT_VERSION) -> JsonObject:
        """List discovered books for a PeopleBooks version."""
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            doc_version = _require_doc_version(repository, version)
            books = repository.list_books(doc_version_id=doc_version.id)
        return {
            "version": _doc_version_payload(doc_version),
            "books": [_book_payload(book) for book in books],
        }

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def health(version: str = DEFAULT_VERSION) -> JsonObject:
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
            return {
                "status": "unavailable",
                "error": {
                    "code": "database_unavailable",
                    "message": str(error),
                },
            }

        return {
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
            return _json(_section_detail_payload(repository, section))

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
) -> JsonObject:
    page = _require_page_by_id(repository, section.page_id)
    version = _require_doc_version_by_id(repository, page.doc_version_id)
    book = _require_book_by_id(repository, page.book_id)
    chunks = repository.list_chunks_for_section(section_id=section.id)

    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "page": _page_payload(page),
        "section": _section_payload(section),
        "chunks": [_chunk_payload(chunk) for chunk in chunks],
    }


def _doc_version_payload(version: DocVersionRecord) -> JsonObject:
    return {
        "id": version.id,
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


def _section_payload(section: SectionRecord) -> JsonObject:
    return {
        "id": section.id,
        "page_id": section.page_id,
        "stable_id": section.stable_id,
        "heading": section.heading,
        "level": section.level,
        "section_path": section.section_path,
        "ordinal": section.ordinal,
        "content": section.content,
    }


def _section_outline_payload(section: SectionRecord) -> JsonObject:
    return {
        "id": section.id,
        "stable_id": section.stable_id,
        "heading": section.heading,
        "level": section.level,
    }


def _chunk_payload(chunk: ChunkRecord) -> JsonObject:
    return {
        "id": chunk.id,
        "stable_id": chunk.stable_id,
        "ordinal": chunk.ordinal,
        "content": chunk.content,
    }


def _search_result_payload(result: SearchResultRecord) -> JsonObject:
    return {
        "version": {
            "code": result.version_code,
        },
        "book": {
            "code": result.book_code,
            "title": result.book_title,
        },
        "page": {
            "page_id": result.page_id,
            "title": result.page_title,
            "normalized_path": result.normalized_path,
            "source_url": result.source_url,
        },
        "section": {
            "section_id": result.section_id,
            "stable_id": result.section_stable_id,
            "heading": result.section_heading,
            "section_path": result.section_path,
        },
        "chunk": {
            "chunk_id": result.chunk_id,
            "stable_id": result.chunk_stable_id,
            "snippet": result.snippet,
            "rank": result.rank,
        },
    }


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _bounded_outline_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _bounded_offset(offset: int) -> int:
    return max(0, offset)


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
