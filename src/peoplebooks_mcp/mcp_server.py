from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from psycopg.errors import QueryCanceled, UndefinedColumn
from pydantic import BaseModel, ConfigDict, Field

from peoplebooks_mcp.config import ToolResultMode, load_config
from peoplebooks_mcp.repositories import (
    EXPECTED_SCHEMA_REVISION,
    BookRecord,
    DocVersionRecord,
    PageRecord,
    PageSearchRecord,
    PeopleBooksRepository,
    SearchResultRecord,
    SectionRecord,
)

JsonObject = dict[str, Any]
logger = logging.getLogger(__name__)
SearchMode = Literal["auto", "exact"]

DEFAULT_VERSION = "pt862"
JSON_MIME_TYPE = "application/json"
DEFAULT_SEARCH_RESPONSE_CHARS = 4000
DEFAULT_SECTION_CHARS = 1200
MAX_RESPONSE_CHARS = 8000
BOOK_PAGES_RESOURCE_LIMIT = 100
MIN_STRICT_AUTO_SCORE = 0.2


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


class BudgetPayload(StrictModel):
    truncated: bool


class SearchResultPayload(StrictModel):
    book_code: str
    page_id: int
    title: str | None = None
    section_id: int
    section_stable_id: str
    path: list[str]
    snippet: str
    source_url: str


class SearchDocsResponse(StrictModel):
    match: str
    truncated: bool
    results: list[SearchResultPayload]
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


class FindPagesResponse(StrictModel):
    pages: list[PageSearchPayload] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


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
    content: str | None = Field(default=None, exclude_if=lambda value: value is None)
    next_cursor: str | None = None
    budget: BudgetPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


class ListBooksResponse(StrictModel):
    version: VersionPayload | None = Field(default=None, exclude_if=lambda value: value is None)
    books: list[BookPayload] | None = Field(default=None, exclude_if=lambda value: value is None)
    error: ErrorDetailPayload | None = Field(default=None, exclude_if=lambda value: value is None)


def _tool_result(
    payload: JsonObject,
    *,
    mode: ToolResultMode,
    is_error: bool = False,
) -> CallToolResult:
    content: list[TextContent] = []
    if is_error:
        error = payload.get("error", {})
        message = str(error.get("message", "The tool call failed."))
        content = [TextContent(type="text", text=message)]
    elif mode == "compatible":
        content = [TextContent(type="text", text=_json(payload))]
    return CallToolResult(
        content=content,
        structuredContent=payload,
        isError=is_error,
    )


def create_server(
    *,
    database_url: str | None = None,
    search_timeout_seconds: float | None = None,
    tool_result_mode: ToolResultMode | None = None,
) -> FastMCP:
    settings = load_config().settings
    resolved_database_url = database_url or settings.database_url
    resolved_search_timeout = (
        settings.search_timeout_seconds
        if search_timeout_seconds is None
        else search_timeout_seconds
    )
    resolved_tool_result_mode = tool_result_mode or settings.tool_result_mode
    if resolved_tool_result_mode not in {"structured", "compatible"}:
        raise ValueError("tool_result_mode must be 'structured' or 'compatible'")

    def tool_result(payload: JsonObject, *, is_error: bool = False) -> CallToolResult:
        return _tool_result(
            payload,
            mode=resolved_tool_result_mode,
            is_error=is_error,
        )

    def unknown_version_result(version: str) -> CallToolResult:
        return tool_result(
            _error_payload(
                code="unknown_version",
                message=(
                    f"Unknown documentation version {version!r}. Use a configured version code "
                    f"such as {DEFAULT_VERSION!r}."
                ),
            ),
            is_error=True,
        )

    def resolve_doc_version(
        repository: PeopleBooksRepository,
        version: str,
    ) -> DocVersionRecord | None:
        # Agents commonly spell the default version as "latest". Treat it as an
        # alias rather than spending a failed call teaching them the seed code.
        version_code = DEFAULT_VERSION if version.strip().lower() == "latest" else version
        return repository.get_doc_version_by_code(version_code)

    def database_error_result(tool_name: str) -> CallToolResult:
        logger.exception("MCP tool %s failed due to an internal database error", tool_name)
        return tool_result(
            _error_payload(
                code="database_error",
                message=(
                    "The documentation database operation failed. Check health and server logs, "
                    "then retry."
                ),
            ),
            is_error=True,
        )

    def search_timeout_result(tool_name: str) -> CallToolResult:
        logger.warning("MCP tool %s exceeded the configured search timeout", tool_name)
        error = {
            "code": "search_timeout",
            "message": (
                f"The {tool_name} query exceeded the configured search timeout. "
                "Narrow the query with book_code or page_id and retry."
            ),
        }
        if tool_name == "search_docs":
            return tool_result(
                {"match": "error", "truncated": False, "results": [], "error": error},
                is_error=True,
            )
        return tool_result({"error": error}, is_error=True)

    server = FastMCP(
        "peoplebooks-mcp",
        instructions=(
            "Read-only Oracle PeopleBooks documentation server backed by local PostgreSQL. "
            "Handlers search and read indexed database content only. For documentation "
            "questions, call search_docs first with the user's wording and answer from its "
            "snippets when sufficient; omit version to use the default. Do not call health, "
            "list_books, or find_pages first. Use find_pages only to locate a page when no "
            "answer text is needed. Use get_section only when a search_docs snippet lacks "
            "enough context, passing the returned section_id unchanged."
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
        query: Annotated[str, Field(description="Question, phrase, heading, or API name to find.")],
        version: Annotated[
            str, Field(description="Configured documentation version code.")
        ] = DEFAULT_VERSION,
        limit: Annotated[int, Field(description="Maximum page-diversified results to return.")] = 5,
        book_code: Annotated[
            str | None,
            Field(description="Optional book code from list_books used to narrow the search."),
        ] = None,
        page_id: Annotated[
            int | None,
            Field(
                description="Optional page_id from search_docs or find_pages to search one page."
            ),
        ] = None,
        search_mode: Annotated[
            SearchMode,
            Field(
                description=(
                    "Use 'exact' for a specific API, page title, or heading; use 'auto' for "
                    "questions and general searches."
                )
            ),
        ] = "auto",
        max_chars: Annotated[
            int,
            Field(
                description=(
                    "Character budget for the complete serialized response, including metadata; "
                    "results are omitted from the end when the budget is reached."
                )
            ),
        ] = DEFAULT_SEARCH_RESPONSE_CHARS,
    ) -> Annotated[CallToolResult, SearchDocsResponse]:
        """Use first for questions or code checks. Returns compact snippets and stable handles."""
        try:
            with PeopleBooksRepository.connect(
                resolved_database_url,
                statement_timeout_seconds=resolved_search_timeout,
            ) as repository:
                doc_version = resolve_doc_version(repository, version)
                if doc_version is None:
                    return unknown_version_result(version)
                bounded_limit = _bounded_limit(limit)
                bounded_max_chars = _bounded_search_response_chars(max_chars)
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
                if search_mode == "auto" and (
                    not results or results[0].rank < MIN_STRICT_AUTO_SCORE
                ):
                    results = repository.search_chunks_relaxed(
                        doc_version_id=doc_version.id,
                        query=query,
                        limit=bounded_limit,
                        book_code=book_code,
                        page_id=page_id,
                    )
                    match_mode = "relaxed" if results else "none"
        except QueryCanceled:
            return search_timeout_result("search_docs")
        except UndefinedColumn:
            logger.warning("Search schema is missing required columns", exc_info=True)
            return tool_result(
                {
                    "match": "error",
                    "truncated": False,
                    "results": [],
                    "error": {
                        "code": "schema_not_ready",
                        "message": (
                            "Search is unavailable because required search columns are missing. "
                            "Run Alembic migrations and re-index the corpus."
                        ),
                        "details": {"expected_revision": EXPECTED_SCHEMA_REVISION},
                    },
                },
                is_error=True,
            )
        except Exception:
            return database_error_result("search_docs")
        return tool_result(
            _search_response_payload(
                match=match_mode,
                results=results,
                max_chars=bounded_max_chars,
            )
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def find_pages(
        query: Annotated[
            str, Field(description="Page title, heading, path fragment, or API name to locate.")
        ],
        version: Annotated[
            str,
            Field(description="Configured version code; omit for pt862. 'latest' is accepted."),
        ] = DEFAULT_VERSION,
        book_code: Annotated[
            str | None,
            Field(description="Optional book code from list_books used to narrow candidates."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum page candidates to return.")] = 10,
    ) -> Annotated[CallToolResult, FindPagesResponse]:
        """Navigation only, not for answering questions. Returns no documentation content."""
        try:
            with PeopleBooksRepository.connect(
                resolved_database_url,
                statement_timeout_seconds=resolved_search_timeout,
            ) as repository:
                doc_version = resolve_doc_version(repository, version)
                if doc_version is None:
                    return unknown_version_result(version)
                pages = repository.find_pages(
                    doc_version_id=doc_version.id,
                    query=query,
                    book_code=book_code,
                    limit=_bounded_limit(limit),
                )
        except QueryCanceled:
            return search_timeout_result("find_pages")
        except Exception:
            return database_error_result("find_pages")
        return tool_result(
            {
                "pages": [_page_search_payload(page) for page in pages],
            }
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def get_page_outline(
        version: Annotated[
            str, Field(description="Configured documentation version code.")
        ] = DEFAULT_VERSION,
        page_id: Annotated[
            int | None,
            Field(description="Preferred page_id returned by search_docs or find_pages."),
        ] = None,
        normalized_path: Annotated[
            str | None, Field(description="Exact normalized path when page_id is unavailable.")
        ] = None,
        limit: Annotated[int, Field(description="Maximum headings to return.")] = 50,
        offset: Annotated[int, Field(description="Zero-based heading offset for pagination.")] = 0,
        max_level: Annotated[
            int | None, Field(description="Optional deepest heading level to include.")
        ] = None,
    ) -> Annotated[CallToolResult, PageDetailResponse]:
        """Use before get_section when only headings and section ids are needed."""
        try:
            with PeopleBooksRepository.connect(resolved_database_url) as repository:
                doc_version = resolve_doc_version(repository, version)
                if doc_version is None:
                    return unknown_version_result(version)
                page = _resolve_page_or_none(
                    repository,
                    doc_version=doc_version,
                    page_id=page_id,
                    normalized_path=normalized_path,
                )
                if page is None:
                    return tool_result(
                        _page_not_found_payload(
                            repository,
                            doc_version=doc_version,
                            page_id=page_id,
                            normalized_path=normalized_path,
                        ),
                        is_error=True,
                    )
                return tool_result(
                    _page_outline_payload(
                        repository,
                        page,
                        limit=limit,
                        offset=offset,
                        max_level=max_level,
                    )
                )
        except Exception:
            return database_error_result("get_page_outline")

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def get_section(
        version: Annotated[
            str, Field(description="Configured documentation version code.")
        ] = DEFAULT_VERSION,
        section_id: Annotated[
            int | None,
            Field(description="Preferred section_id returned by search_docs or get_page_outline."),
        ] = None,
        section_stable_id: Annotated[
            str | None,
            Field(description="Stable section identifier, used together with a page identifier."),
        ] = None,
        page_id: Annotated[
            int | None, Field(description="Page identifier used to resolve section_stable_id.")
        ] = None,
        normalized_path: Annotated[
            str | None, Field(description="Exact page path used to resolve section_stable_id.")
        ] = None,
        max_chars: Annotated[
            int,
            Field(description="Character budget for Markdown content only, excluding metadata."),
        ] = DEFAULT_SECTION_CHARS,
        cursor: Annotated[
            str | None,
            Field(
                description=(
                    "Opaque next_cursor from the preceding response; reuse it unchanged with the "
                    "same section identifier to continue without gaps or duplication."
                )
            ),
        ] = None,
    ) -> Annotated[CallToolResult, SectionDetailResponse]:
        """Use after search_docs or get_page_outline. Returns paged Markdown without duplication."""
        try:
            with PeopleBooksRepository.connect(resolved_database_url) as repository:
                doc_version = resolve_doc_version(repository, version)
                if doc_version is None:
                    return unknown_version_result(version)
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
                    return tool_result(
                        _error_payload(
                            code="section_not_found",
                            message=(
                                f"{error}. Use a section_id returned by search_docs or "
                                "get_page_outline, then retry."
                            ),
                        ),
                        is_error=True,
                    )
                try:
                    return tool_result(
                        _section_detail_payload(
                            repository,
                            section,
                            max_chars=max_chars,
                            cursor=cursor,
                        )
                    )
                except ValueError as error:
                    return tool_result(
                        _error_payload(code="invalid_cursor", message=str(error)),
                        is_error=True,
                    )
        except Exception:
            return database_error_result("get_section")

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def list_books(
        version: Annotated[
            str, Field(description="Configured documentation version code.")
        ] = DEFAULT_VERSION,
    ) -> Annotated[CallToolResult, ListBooksResponse]:
        """List book codes for scoping later search_docs or find_pages calls."""
        try:
            with PeopleBooksRepository.connect(resolved_database_url) as repository:
                doc_version = resolve_doc_version(repository, version)
                if doc_version is None:
                    return unknown_version_result(version)
                books = repository.list_books(doc_version_id=doc_version.id)
        except Exception:
            return database_error_result("list_books")
        return tool_result(
            {
                "version": _doc_version_payload(doc_version),
                "books": [_book_payload(book) for book in books],
            }
        )

    @server.tool(
        annotations=read_only,
        structured_output=True,
    )
    def health(
        version: Annotated[
            str, Field(description="Configured documentation version code to check for readiness.")
        ] = DEFAULT_VERSION,
    ) -> Annotated[CallToolResult, JsonObject]:
        """Report schema and index readiness for agent querying."""
        try:
            with PeopleBooksRepository.connect(resolved_database_url) as repository:
                schema_revision = repository.get_schema_revision()
                missing_columns = repository.list_missing_required_columns()
                schema_is_current = schema_revision == EXPECTED_SCHEMA_REVISION
                doc_version = resolve_doc_version(repository, version)
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
        except Exception:
            logger.exception("MCP health tool could not access the documentation database")
            return tool_result(
                {
                    "status": "unavailable",
                    "error": {
                        "code": "database_unavailable",
                        "message": (
                            "The documentation database is unavailable. Check connection settings "
                            "and server logs, then retry."
                        ),
                    },
                },
                is_error=True,
            )

        return tool_result(
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
        description="Read the first 100 discovered pages for a PeopleBooks book.",
        mime_type=JSON_MIME_TYPE,
    )
    def pages_resource(version_code: str, book_code: str) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            version = _require_doc_version(repository, version_code)
            book = _require_book(repository, doc_version_id=version.id, code=book_code)
            return _json(_book_pages_payload(repository, version=version, book=book, offset=0))

    @server.resource(
        "peoplebooks://versions/{version_code}/books/{book_code}/pages/{offset}",
        name="peoplebooks_pages_page",
        title="PeopleBooks Pages Page",
        description="Read up to 100 discovered book pages starting at an offset.",
        mime_type=JSON_MIME_TYPE,
    )
    def pages_page_resource(version_code: str, book_code: str, offset: int) -> str:
        with PeopleBooksRepository.connect(resolved_database_url) as repository:
            version = _require_doc_version(repository, version_code)
            book = _require_book(repository, doc_version_id=version.id, code=book_code)
            return _json(_book_pages_payload(repository, version=version, book=book, offset=offset))

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
                    max_chars=DEFAULT_SECTION_CHARS,
                    cursor=None,
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
    max_chars: int,
    cursor: str | None,
) -> JsonObject:
    page = _require_page_by_id(repository, section.page_id)
    version = _require_doc_version_by_id(repository, page.doc_version_id)
    book = _require_book_by_id(repository, page.book_id)
    bounded_max_chars = _bounded_max_chars(max_chars, default=DEFAULT_SECTION_CHARS)
    offset = _decode_section_cursor(cursor, section=section) if cursor else 0
    content, next_offset = _section_content_page(
        section.content,
        offset=offset,
        max_chars=bounded_max_chars,
    )
    next_cursor = (
        _encode_section_cursor(section=section, offset=next_offset)
        if next_offset is not None
        else None
    )
    section_payload = _section_payload(section)

    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "page": _page_payload(page),
        "section": section_payload,
        "content": content,
        "next_cursor": next_cursor,
        "budget": {
            "truncated": next_cursor is not None,
        },
    }


def _section_content_page(
    content: str,
    *,
    offset: int,
    max_chars: int,
) -> tuple[str, int | None]:
    if offset < 0 or offset > len(content):
        raise ValueError("The continuation cursor points outside this section.")
    if offset == len(content):
        return "", None

    hard_end = min(len(content), offset + max_chars)
    if hard_end == len(content):
        return content[offset:], None

    end = hard_end
    block_boundary = content.rfind("\n\n", offset + 40, hard_end)
    if block_boundary >= 0:
        end = block_boundary + 2
    else:
        line_boundary = content.rfind("\n", offset + 40, hard_end)
        if line_boundary >= 0:
            end = line_boundary + 1
    return content[offset:end], end


def _encode_section_cursor(*, section: SectionRecord, offset: int) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "section_id": section.id,
            "section": section.stable_id,
            "content": hashlib.sha256(section.content.encode()).hexdigest()[:16],
            "offset": offset,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _decode_section_cursor(cursor: str, *, section: SectionRecord) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(cursor + padding, altchars=b"-_", validate=True))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("The continuation cursor is invalid; restart without a cursor.") from error
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError(
            "The continuation cursor version is unsupported; restart without a cursor."
        )
    if payload.get("section_id") != section.id or payload.get("section") != section.stable_id:
        raise ValueError("The continuation cursor belongs to a different section.")
    content_digest = hashlib.sha256(section.content.encode()).hexdigest()[:16]
    if payload.get("content") != content_digest:
        raise ValueError(
            "The section changed after this cursor was issued; restart without a cursor."
        )
    offset = payload.get("offset")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError("The continuation cursor has an invalid offset.")
    return offset


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


def _book_pages_payload(
    repository: PeopleBooksRepository,
    *,
    version: DocVersionRecord,
    book: BookRecord,
    offset: int,
) -> JsonObject:
    bounded_offset = max(0, offset)
    page_window = repository.list_pages_for_book(
        doc_version_id=version.id,
        book_id=book.id,
        limit=BOOK_PAGES_RESOURCE_LIMIT + 1,
        offset=bounded_offset,
    )
    pages = page_window[:BOOK_PAGES_RESOURCE_LIMIT]
    next_offset = (
        bounded_offset + BOOK_PAGES_RESOURCE_LIMIT
        if len(page_window) > BOOK_PAGES_RESOURCE_LIMIT
        else None
    )
    next_uri = None
    if next_offset is not None:
        next_uri = f"peoplebooks://versions/{version.code}/books/{book.code}/pages/{next_offset}"
    return {
        "version": _doc_version_payload(version),
        "book": _book_payload(book),
        "offset": bounded_offset,
        "returned_count": len(pages),
        "next_uri": next_uri,
        "pages": [_page_payload(page) for page in pages],
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
    }


def _section_outline_payload(section: SectionRecord) -> JsonObject:
    return {
        "id": section.id,
        "stable_id": section.stable_id,
        "heading": section.heading,
        "level": section.level,
    }


def _search_result_payload(result: SearchResultRecord) -> JsonObject:
    path = list(result.section_path)
    if path and result.page_title and path[0] == result.page_title:
        path = path[1:]
    return {
        "book_code": result.book_code,
        "page_id": result.page_id,
        "title": result.page_title,
        "section_id": result.section_id,
        "section_stable_id": result.section_stable_id,
        "path": path,
        "snippet": _strip_search_markup(result.snippet),
        "source_url": result.source_url,
    }


def _search_response_payload(
    *,
    match: str,
    results: Sequence[SearchResultRecord],
    max_chars: int,
) -> JsonObject:
    payloads = [_search_result_payload(result) for result in results]
    complete = {"match": match, "truncated": False, "results": payloads}
    if len(_json(complete)) <= max_chars:
        return complete

    full_snippets = [str(payload["snippet"]) for payload in payloads]
    while payloads:
        empty = [dict(payload, snippet="") for payload in payloads]
        candidate = {"match": match, "truncated": True, "results": empty}
        if len(_json(candidate)) <= max_chars:
            break
        payloads.pop()
        full_snippets.pop()

    if not payloads:
        return {"match": match, "truncated": bool(results), "results": []}

    low = 0
    high = max(len(snippet) for snippet in full_snippets)
    best = {"match": match, "truncated": True, "results": []}
    while low <= high:
        snippet_limit = (low + high) // 2
        candidate_results = []
        for payload, snippet in zip(payloads, full_snippets, strict=True):
            truncated_snippet, _ = _truncate_text(snippet, max_chars=snippet_limit)
            candidate_results.append(dict(payload, snippet=truncated_snippet))
        candidate = {"match": match, "truncated": True, "results": candidate_results}
        if len(_json(candidate)) <= max_chars:
            best = candidate
            low = snippet_limit + 1
        else:
            high = snippet_limit - 1
    return best


def _strip_search_markup(text: str) -> str:
    return text.replace("<mark>", "").replace("</mark>", "")


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _bounded_max_chars(max_chars: int, *, default: int) -> int:
    if max_chars < 1:
        return default
    return max(40, min(max_chars, MAX_RESPONSE_CHARS))


def _bounded_search_response_chars(max_chars: int) -> int:
    if max_chars < 1:
        return DEFAULT_SEARCH_RESPONSE_CHARS
    return max(256, min(max_chars, MAX_RESPONSE_CHARS))


def _bounded_outline_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _bounded_offset(offset: int) -> int:
    return max(0, offset)


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
                "Provide either page_id returned by search/find_pages or an exact normalized_path."
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
            "message": (
                "No page matched the supplied identifier. Use a suggested page or call "
                "find_pages, then retry with its page_id."
            ),
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
