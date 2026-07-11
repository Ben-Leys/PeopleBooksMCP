from __future__ import annotations

import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

import psycopg
from psycopg.errors import UndefinedTable, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from peoplebooks_mcp.database import connect

JsonObject = dict[str, Any]
EXPECTED_SCHEMA_REVISION = "0003_hybrid_search"
REQUIRED_SCHEMA_COLUMNS = (
    ("chunks", "search_vector"),
    ("chunks", "simple_search_vector"),
    ("chunks", "identifier_text"),
)
QUERY_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_'-]*", re.IGNORECASE)
QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
PAGE_METADATA_COLUMNS = """
    id,
    doc_version_id,
    book_id,
    nav_node_id,
    normalized_url,
    normalized_path,
    source_url,
    title,
    source_metadata,
    NULL::text AS raw_html,
    content_hash,
    parser_version,
    fetch_status,
    queued_at,
    fetched_at,
    parsed_at,
    indexed_at,
    created_at,
    updated_at
"""
CHUNK_CONTENT_COLUMNS = """
    id,
    page_id,
    section_id,
    stable_id,
    ordinal,
    content,
    metadata,
    NULL::tsvector AS search_vector,
    created_at,
    updated_at
"""


@dataclass(frozen=True, slots=True)
class DocVersionRecord:
    id: int
    code: str
    label: str
    seed_url: str
    source_metadata: JsonObject
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BookRecord:
    id: int
    doc_version_id: int
    code: str
    title: str
    seed_url: str
    source_metadata: JsonObject
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NavNodeRecord:
    id: int
    doc_version_id: int
    book_id: int
    parent_id: int | None
    stable_id: str
    title: str
    node_type: str
    normalized_url: str | None
    source_url: str | None
    position: int
    source_metadata: JsonObject
    discovered_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PageRecord:
    id: int
    doc_version_id: int
    book_id: int
    nav_node_id: int | None
    normalized_url: str
    normalized_path: str
    source_url: str
    title: str | None
    source_metadata: JsonObject
    raw_html: str | None
    content_hash: str | None
    parser_version: str | None
    fetch_status: str
    queued_at: datetime
    fetched_at: datetime | None
    parsed_at: datetime | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SectionRecord:
    id: int
    page_id: int
    stable_id: str
    heading: str
    level: int
    section_path: list[str]
    ordinal: int
    content: str
    parser_version: str
    source_metadata: JsonObject
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    id: int
    page_id: int
    section_id: int
    stable_id: str
    ordinal: int
    content: str
    metadata: JsonObject
    search_vector: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FetchEventRecord:
    id: int
    page_id: int
    event_type: str
    fetch_status: str
    status_code: int | None
    error_message: str | None
    elapsed_ms: int | None
    content_hash: str | None
    source_url: str
    metadata: JsonObject
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StatusCounts:
    discovered: int
    queued: int
    fetched: int
    failed: int
    parsed: int
    indexed: int


@dataclass(frozen=True, slots=True)
class SearchResultRecord:
    version_code: str
    version_label: str
    book_code: str
    book_title: str
    page_id: int
    page_title: str | None
    normalized_path: str
    source_url: str
    page_source_metadata: JsonObject
    section_id: int
    section_stable_id: str
    section_heading: str
    section_path: list[str]
    chunk_id: int
    chunk_stable_id: str
    snippet: str
    rank: float


@dataclass(frozen=True, slots=True)
class PageSearchRecord:
    id: int
    doc_version_id: int
    book_id: int
    book_code: str
    book_title: str
    title: str | None
    normalized_path: str
    source_url: str
    fetch_status: str
    matched_terms: int
    score: float


@dataclass(frozen=True, slots=True)
class ContentHealthRecord:
    total_pages: int
    parsed_pages: int
    indexed_pages: int
    total_chunks: int
    indexed_chunks: int


@dataclass(frozen=True, slots=True)
class ChunkInput:
    stable_id: str
    ordinal: int
    content: str
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class SectionInput:
    stable_id: str
    heading: str
    level: int
    section_path: Sequence[str]
    ordinal: int
    content: str
    chunks: Sequence[ChunkInput]
    source_metadata: JsonObject


class PeopleBooksRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        *,
        statement_timeout_seconds: float | None = None,
    ) -> None:
        self._connection = connection
        self._connection.row_factory = dict_row
        if statement_timeout_seconds is not None:
            timeout_ms = max(1, round(statement_timeout_seconds * 1000))
            self._connection.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (f"{timeout_ms}ms",),
            )

    @classmethod
    @contextmanager
    def connect(
        cls,
        database_url: str,
        *,
        statement_timeout_seconds: float | None = None,
    ) -> Iterator[Self]:
        with connect(database_url) as connection:
            yield cls(connection, statement_timeout_seconds=statement_timeout_seconds)

    @property
    def connection(self) -> psycopg.Connection:
        return self._connection

    def upsert_doc_version(
        self,
        *,
        code: str,
        label: str,
        seed_url: str,
        source_metadata: JsonObject | None = None,
    ) -> DocVersionRecord:
        row = self._connection.execute(
            """
            INSERT INTO doc_versions (code, label, seed_url, source_metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET label = EXCLUDED.label,
                seed_url = EXCLUDED.seed_url,
                source_metadata = doc_versions.source_metadata || EXCLUDED.source_metadata,
                updated_at = now()
            RETURNING *
            """,
            (code, label, seed_url, Jsonb(source_metadata or {})),
        ).fetchone()
        return _record(DocVersionRecord, row)

    def get_doc_version_by_code(self, code: str) -> DocVersionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM doc_versions WHERE code = %s",
            (code,),
        ).fetchone()
        return _optional_record(DocVersionRecord, row)

    def get_doc_version_by_id(self, doc_version_id: int) -> DocVersionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM doc_versions WHERE id = %s",
            (doc_version_id,),
        ).fetchone()
        return _optional_record(DocVersionRecord, row)

    def list_doc_versions(self) -> list[DocVersionRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM doc_versions
            ORDER BY code
            """
        ).fetchall()
        return [_record(DocVersionRecord, row) for row in rows]

    def get_schema_revision(self) -> str | None:
        try:
            row = self._connection.execute(
                """
                SELECT version_num
                FROM alembic_version
                ORDER BY version_num DESC
                LIMIT 1
                """
            ).fetchone()
        except UndefinedTable:
            return None
        if row is None:
            return None
        return row["version_num"]

    def list_missing_required_columns(self) -> list[str]:
        missing: list[str] = []
        for table_name, column_name in REQUIRED_SCHEMA_COLUMNS:
            row = self._connection.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                """,
                (table_name, column_name),
            ).fetchone()
            if row is None:
                missing.append(f"{table_name}.{column_name}")
        return missing

    def get_content_health(
        self,
        *,
        doc_version_id: int,
        include_index_counts: bool,
    ) -> ContentHealthRecord:
        if include_index_counts:
            row = self._connection.execute(
                """
                SELECT
                    count(DISTINCT p.id)::int AS total_pages,
                    count(DISTINCT p.id) FILTER (
                        WHERE p.fetch_status IN ('parsed', 'indexed')
                    )::int AS parsed_pages,
                    count(DISTINCT p.id) FILTER (
                        WHERE p.fetch_status = 'indexed'
                    )::int AS indexed_pages,
                    count(c.id)::int AS total_chunks,
                    count(c.search_vector)::int AS indexed_chunks
                FROM pages AS p
                LEFT JOIN chunks AS c ON c.page_id = p.id
                WHERE p.doc_version_id = %s
                """,
                (doc_version_id,),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT
                    count(DISTINCT p.id)::int AS total_pages,
                    count(DISTINCT p.id) FILTER (
                        WHERE p.fetch_status IN ('parsed', 'indexed')
                    )::int AS parsed_pages,
                    count(DISTINCT p.id) FILTER (
                        WHERE p.fetch_status = 'indexed'
                    )::int AS indexed_pages,
                    count(c.id)::int AS total_chunks,
                    0::int AS indexed_chunks
                FROM pages AS p
                LEFT JOIN chunks AS c ON c.page_id = p.id
                WHERE p.doc_version_id = %s
                """,
                (doc_version_id,),
            ).fetchone()
        return _record(ContentHealthRecord, row)

    def upsert_book(
        self,
        *,
        doc_version_id: int,
        code: str,
        title: str,
        seed_url: str,
        source_metadata: JsonObject | None = None,
    ) -> BookRecord:
        row = self._connection.execute(
            """
            INSERT INTO books (doc_version_id, code, title, seed_url, source_metadata)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (doc_version_id, code) DO UPDATE
            SET title = EXCLUDED.title,
                seed_url = EXCLUDED.seed_url,
                source_metadata = books.source_metadata || EXCLUDED.source_metadata,
                updated_at = now()
            RETURNING *
            """,
            (doc_version_id, code, title, seed_url, Jsonb(source_metadata or {})),
        ).fetchone()
        return _record(BookRecord, row)

    def get_book_by_code(self, *, doc_version_id: int, code: str) -> BookRecord | None:
        row = self._connection.execute(
            "SELECT * FROM books WHERE doc_version_id = %s AND code = %s",
            (doc_version_id, code),
        ).fetchone()
        return _optional_record(BookRecord, row)

    def get_book_by_id(self, book_id: int) -> BookRecord | None:
        row = self._connection.execute(
            "SELECT * FROM books WHERE id = %s",
            (book_id,),
        ).fetchone()
        return _optional_record(BookRecord, row)

    def list_books(self, *, doc_version_id: int) -> list[BookRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM books
            WHERE doc_version_id = %s
            ORDER BY code
            """,
            (doc_version_id,),
        ).fetchall()
        return [_record(BookRecord, row) for row in rows]

    def list_nav_nodes(self, *, doc_version_id: int) -> list[NavNodeRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM nav_nodes
            WHERE doc_version_id = %s
            ORDER BY id
            """,
            (doc_version_id,),
        ).fetchall()
        return [_record(NavNodeRecord, row) for row in rows]

    def upsert_nav_node(
        self,
        *,
        doc_version_id: int,
        book_id: int,
        parent_id: int | None,
        stable_id: str,
        title: str,
        node_type: str,
        normalized_url: str | None,
        source_url: str | None,
        position: int,
        source_metadata: JsonObject | None = None,
    ) -> NavNodeRecord:
        row = self._connection.execute(
            """
            INSERT INTO nav_nodes (
                doc_version_id,
                book_id,
                parent_id,
                stable_id,
                title,
                node_type,
                normalized_url,
                source_url,
                position,
                source_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (book_id, stable_id) DO UPDATE
            SET parent_id = EXCLUDED.parent_id,
                title = EXCLUDED.title,
                node_type = EXCLUDED.node_type,
                normalized_url = EXCLUDED.normalized_url,
                source_url = EXCLUDED.source_url,
                position = EXCLUDED.position,
                source_metadata = nav_nodes.source_metadata || EXCLUDED.source_metadata,
                updated_at = now()
            RETURNING *
            """,
            (
                doc_version_id,
                book_id,
                parent_id,
                stable_id,
                title,
                node_type,
                normalized_url,
                source_url,
                position,
                Jsonb(source_metadata or {}),
            ),
        ).fetchone()
        return _record(NavNodeRecord, row)

    def queue_page(
        self,
        *,
        doc_version_id: int,
        book_id: int,
        normalized_url: str,
        normalized_path: str,
        source_url: str,
        nav_node_id: int | None = None,
        title: str | None = None,
        source_metadata: JsonObject | None = None,
    ) -> PageRecord:
        existing_page = self._find_page_by_unique_key(
            doc_version_id=doc_version_id,
            normalized_url=normalized_url,
            normalized_path=normalized_path,
        )
        if existing_page is not None:
            return self._refresh_page_discovery(
                page_id=existing_page.id,
                book_id=book_id,
                nav_node_id=nav_node_id,
                source_url=source_url,
                title=title,
                source_metadata=source_metadata,
            )

        try:
            row = self._connection.execute(
                """
                INSERT INTO pages (
                    doc_version_id,
                    book_id,
                    nav_node_id,
                    normalized_url,
                    normalized_path,
                    source_url,
                    title,
                    source_metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    doc_version_id,
                    book_id,
                    nav_node_id,
                    normalized_url,
                    normalized_path,
                    source_url,
                    title,
                    Jsonb(source_metadata or {}),
                ),
            ).fetchone()
        except UniqueViolation:
            row = self._find_page_by_unique_key(
                doc_version_id=doc_version_id,
                normalized_url=normalized_url,
                normalized_path=normalized_path,
            )
        return _record(PageRecord, row)

    def list_next_queued_pages(self, *, doc_version_id: int, limit: int) -> list[PageRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM pages
            WHERE doc_version_id = %s
              AND fetch_status = 'queued'
            ORDER BY queued_at, id
            LIMIT %s
            """,
            (doc_version_id, limit),
        ).fetchall()
        return [_record(PageRecord, row) for row in rows]

    def list_next_scrape_pages(self, *, doc_version_id: int, limit: int) -> list[PageRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM pages
            WHERE doc_version_id = %s
              AND (
                fetch_status = 'queued'
                OR (fetch_status = 'fetched' AND raw_html IS NOT NULL)
              )
            ORDER BY queued_at, id
            LIMIT %s
            """,
            (doc_version_id, limit),
        ).fetchall()
        return [_record(PageRecord, row) for row in rows]

    def list_pages_with_raw_html(self, *, doc_version_id: int) -> list[PageRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM pages
            WHERE doc_version_id = %s
              AND raw_html IS NOT NULL
            ORDER BY id
            """,
            (doc_version_id,),
        ).fetchall()
        return [_record(PageRecord, row) for row in rows]

    def list_pages_for_book(self, *, doc_version_id: int, book_id: int) -> list[PageRecord]:
        rows = self._connection.execute(
            f"""
            SELECT {PAGE_METADATA_COLUMNS}
            FROM pages
            WHERE doc_version_id = %s
              AND book_id = %s
            ORDER BY normalized_path, id
            """,
            (doc_version_id, book_id),
        ).fetchall()
        return [_record(PageRecord, row) for row in rows]

    def find_pages(
        self,
        *,
        doc_version_id: int,
        query: str,
        book_code: str | None = None,
        limit: int = 10,
    ) -> list[PageSearchRecord]:
        terms = _query_terms(query)
        bounded_limit = max(1, min(limit, 50))
        if not terms:
            rows = self._connection.execute(
                """
                SELECT
                    p.id,
                    p.doc_version_id,
                    p.book_id,
                    b.code AS book_code,
                    b.title AS book_title,
                    p.title,
                    p.normalized_path,
                    p.source_url,
                    p.fetch_status,
                    0::int AS matched_terms,
                    0::float8 AS score
                FROM pages AS p
                JOIN books AS b ON b.id = p.book_id
                WHERE p.doc_version_id = %s
                  AND p.fetch_status IN ('parsed', 'indexed')
                  AND (%s::text IS NULL OR b.code = %s)
                ORDER BY p.id
                LIMIT %s
                """,
                (doc_version_id, book_code, book_code, bounded_limit),
            ).fetchall()
            return [_record(PageSearchRecord, row) for row in rows]

        rows = self._connection.execute(
            """
            WITH query_terms AS (
                SELECT unnest(%s::text[]) AS term
            ),
            scored AS (
                SELECT
                    p.id,
                    p.doc_version_id,
                    p.book_id,
                    b.code AS book_code,
                    b.title AS book_title,
                    p.title,
                    p.normalized_path,
                    p.source_url,
                    p.fetch_status,
                    count(DISTINCT qt.term) FILTER (
                        WHERE lower(
                            coalesce(b.title, '') || ' ' ||
                            coalesce(p.title, '') || ' ' ||
                            coalesce(array_to_string(s.section_path, ' '), '') || ' ' ||
                            coalesce(s.heading, '') || ' ' ||
                            coalesce(c.content, '') || ' ' ||
                            coalesce(p.normalized_path, '')
                        ) LIKE ('%%' || qt.term || '%%')
                    )::int AS matched_terms,
                    (
                        count(DISTINCT qt.term) FILTER (
                            WHERE lower(coalesce(b.title, '')) LIKE ('%%' || qt.term || '%%')
                        ) * 1.0
                        + count(DISTINCT qt.term) FILTER (
                            WHERE lower(coalesce(p.title, '')) LIKE ('%%' || qt.term || '%%')
                        ) * 2.0
                        + count(DISTINCT qt.term) FILTER (
                            WHERE lower(
                                coalesce(array_to_string(s.section_path, ' '), '') || ' ' ||
                                coalesce(s.heading, '')
                            ) LIKE ('%%' || qt.term || '%%')
                        ) * 2.0
                        + count(DISTINCT qt.term) FILTER (
                            WHERE lower(coalesce(c.content, '')) LIKE ('%%' || qt.term || '%%')
                        ) * 10.0
                        + count(DISTINCT qt.term) FILTER (
                            WHERE lower(coalesce(p.normalized_path, '')) LIKE (
                                '%%' || qt.term || '%%'
                            )
                        ) * 0.5
                    )::float8 AS score
                FROM pages AS p
                JOIN books AS b ON b.id = p.book_id
                LEFT JOIN sections AS s ON s.page_id = p.id
                LEFT JOIN chunks AS c ON c.section_id = s.id
                CROSS JOIN query_terms AS qt
                WHERE p.doc_version_id = %s
                  AND p.fetch_status IN ('parsed', 'indexed')
                  AND (%s::text IS NULL OR b.code = %s)
                GROUP BY
                    p.id,
                    p.doc_version_id,
                    p.book_id,
                    b.code,
                    b.title,
                    p.title,
                    p.normalized_path,
                    p.source_url,
                    p.fetch_status
            )
            SELECT *
            FROM scored
            WHERE matched_terms > 0
            ORDER BY matched_terms DESC, score DESC, id
            LIMIT %s
            """,
            (terms, doc_version_id, book_code, book_code, bounded_limit),
        ).fetchall()
        return [_record(PageSearchRecord, row) for row in rows]

    def suggest_pages_for_path(
        self,
        *,
        doc_version_id: int,
        normalized_path: str,
        limit: int = 5,
    ) -> list[PageSearchRecord]:
        bounded_limit = max(1, min(limit, 10))
        path = normalized_path.strip()
        if not path:
            return []

        suffix_rows = self._connection.execute(
            """
            SELECT
                p.id,
                p.doc_version_id,
                p.book_id,
                b.code AS book_code,
                b.title AS book_title,
                p.title,
                p.normalized_path,
                p.source_url,
                p.fetch_status,
                1::int AS matched_terms,
                100::float8 AS score
            FROM pages AS p
            JOIN books AS b ON b.id = p.book_id
            WHERE p.doc_version_id = %s
              AND p.fetch_status IN ('parsed', 'indexed')
              AND (
                p.normalized_path ILIKE ('%%' || %s)
                OR p.normalized_url ILIKE ('%%' || %s)
              )
            ORDER BY length(p.normalized_path), p.id
            LIMIT %s
            """,
            (doc_version_id, path, path, bounded_limit),
        ).fetchall()
        if suffix_rows:
            return [_record(PageSearchRecord, row) for row in suffix_rows]

        stem = _path_stem(path)
        if stem:
            book_rows = self._connection.execute(
                """
                SELECT
                    p.id,
                    p.doc_version_id,
                    p.book_id,
                    b.code AS book_code,
                    b.title AS book_title,
                    p.title,
                    p.normalized_path,
                    p.source_url,
                    p.fetch_status,
                    1::int AS matched_terms,
                    50::float8 AS score
                FROM pages AS p
                JOIN books AS b ON b.id = p.book_id
                WHERE p.doc_version_id = %s
                  AND p.fetch_status IN ('parsed', 'indexed')
                  AND b.code = %s
                ORDER BY p.id
                LIMIT %s
                """,
                (doc_version_id, stem, bounded_limit),
            ).fetchall()
            if book_rows:
                return [_record(PageSearchRecord, row) for row in book_rows]

        return self.find_pages(
            doc_version_id=doc_version_id,
            query=path,
            book_code=None,
            limit=bounded_limit,
        )

    def get_page_by_id(self, page_id: int) -> PageRecord | None:
        row = self._connection.execute(
            f"""
            SELECT {PAGE_METADATA_COLUMNS}
            FROM pages
            WHERE id = %s
            """,
            (page_id,),
        ).fetchone()
        return _optional_record(PageRecord, row)

    def get_page_by_normalized_path(
        self,
        *,
        doc_version_id: int,
        normalized_path: str,
    ) -> PageRecord | None:
        row = self._connection.execute(
            f"""
            SELECT {PAGE_METADATA_COLUMNS}
            FROM pages
            WHERE doc_version_id = %s
              AND normalized_path = %s
            """,
            (doc_version_id, normalized_path),
        ).fetchone()
        return _optional_record(PageRecord, row)

    def get_status_counts(self, *, doc_version_id: int) -> StatusCounts:
        rows = self._connection.execute(
            """
            SELECT fetch_status, count(*) AS page_count
            FROM pages
            WHERE doc_version_id = %s
            GROUP BY fetch_status
            """,
            (doc_version_id,),
        ).fetchall()
        by_status = {row["fetch_status"]: row["page_count"] for row in rows}
        return StatusCounts(
            discovered=sum(by_status.values()),
            queued=by_status.get("queued", 0),
            fetched=by_status.get("fetched", 0),
            failed=by_status.get("failed", 0),
            parsed=by_status.get("parsed", 0),
            indexed=by_status.get("indexed", 0),
        )

    def mark_page_fetched(
        self,
        *,
        page_id: int,
        raw_html: str,
        content_hash: str,
        source_metadata: JsonObject | None = None,
    ) -> PageRecord:
        row = self._connection.execute(
            """
            UPDATE pages
            SET raw_html = %s,
                content_hash = %s,
                fetch_status = 'fetched',
                fetched_at = now(),
                source_metadata = source_metadata || %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (raw_html, content_hash, Jsonb(source_metadata or {}), page_id),
        ).fetchone()
        return _record(PageRecord, row)

    def record_fetch_success(
        self,
        *,
        page_id: int,
        raw_html: str,
        content_hash: str,
        status_code: int,
        elapsed_ms: int | None,
        source_url: str,
        source_metadata: JsonObject | None = None,
        metadata: JsonObject | None = None,
    ) -> tuple[PageRecord, FetchEventRecord]:
        with self._connection.transaction():
            page = self.mark_page_fetched(
                page_id=page_id,
                raw_html=raw_html,
                content_hash=content_hash,
                source_metadata=source_metadata,
            )
            event = self.record_fetch_event(
                page_id=page_id,
                event_type="fetch_succeeded",
                fetch_status="fetched",
                status_code=status_code,
                error_message=None,
                elapsed_ms=elapsed_ms,
                content_hash=content_hash,
                source_url=source_url,
                metadata=metadata,
            )
        return page, event

    def mark_page_failed(
        self,
        *,
        page_id: int,
        source_metadata: JsonObject | None = None,
    ) -> PageRecord:
        row = self._connection.execute(
            """
            UPDATE pages
            SET fetch_status = 'failed',
                source_metadata = source_metadata || %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (Jsonb(source_metadata or {}), page_id),
        ).fetchone()
        return _record(PageRecord, row)

    def record_fetch_failure(
        self,
        *,
        page_id: int,
        error_message: str,
        status_code: int | None,
        elapsed_ms: int | None,
        source_url: str,
        source_metadata: JsonObject | None = None,
        metadata: JsonObject | None = None,
    ) -> tuple[PageRecord, FetchEventRecord]:
        with self._connection.transaction():
            page = self.mark_page_failed(
                page_id=page_id,
                source_metadata=source_metadata,
            )
            event = self.record_fetch_event(
                page_id=page_id,
                event_type="fetch_failed",
                fetch_status="failed",
                status_code=status_code,
                error_message=error_message,
                elapsed_ms=elapsed_ms,
                content_hash=None,
                source_url=source_url,
                metadata=metadata,
            )
        return page, event

    def record_fetch_event(
        self,
        *,
        page_id: int,
        event_type: str,
        fetch_status: str,
        status_code: int | None,
        error_message: str | None,
        elapsed_ms: int | None,
        content_hash: str | None,
        source_url: str,
        metadata: JsonObject | None = None,
    ) -> FetchEventRecord:
        row = self._connection.execute(
            """
            INSERT INTO fetch_events (
                page_id,
                event_type,
                fetch_status,
                status_code,
                error_message,
                elapsed_ms,
                content_hash,
                source_url,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                page_id,
                event_type,
                fetch_status,
                status_code,
                error_message,
                elapsed_ms,
                content_hash,
                source_url,
                Jsonb(metadata or {}),
            ),
        ).fetchone()
        return _record(FetchEventRecord, row)

    def list_fetch_events(self, *, page_id: int) -> list[FetchEventRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM fetch_events
            WHERE page_id = %s
            ORDER BY created_at, id
            """,
            (page_id,),
        ).fetchall()
        return [_record(FetchEventRecord, row) for row in rows]

    def replace_page_sections(
        self,
        *,
        page_id: int,
        parser_version: str,
        sections: Sequence[SectionInput],
    ) -> None:
        with self._connection.transaction():
            retained_section_ids: list[str] = []
            for section in sections:
                retained_section_ids.append(section.stable_id)
                section_row = self._connection.execute(
                    """
                    INSERT INTO sections (
                        page_id,
                        stable_id,
                        heading,
                        level,
                        section_path,
                        ordinal,
                        content,
                        parser_version,
                        source_metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (page_id, stable_id) DO UPDATE
                    SET heading = EXCLUDED.heading,
                        level = EXCLUDED.level,
                        section_path = EXCLUDED.section_path,
                        ordinal = EXCLUDED.ordinal,
                        content = EXCLUDED.content,
                        parser_version = EXCLUDED.parser_version,
                        source_metadata = EXCLUDED.source_metadata,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        page_id,
                        section.stable_id,
                        section.heading,
                        section.level,
                        list(section.section_path),
                        section.ordinal,
                        section.content,
                        parser_version,
                        Jsonb(section.source_metadata),
                    ),
                ).fetchone()
                section_record = _record(SectionRecord, section_row)

                retained_chunk_ids: list[str] = []
                for chunk in section.chunks:
                    retained_chunk_ids.append(chunk.stable_id)
                    self._connection.execute(
                        """
                        INSERT INTO chunks (
                            page_id,
                            section_id,
                            stable_id,
                            ordinal,
                            content,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (section_id, stable_id) DO UPDATE
                        SET page_id = EXCLUDED.page_id,
                            ordinal = EXCLUDED.ordinal,
                            content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            search_vector = NULL,
                            updated_at = now()
                        """,
                        (
                            page_id,
                            section_record.id,
                            chunk.stable_id,
                            chunk.ordinal,
                            chunk.content,
                            Jsonb(chunk.metadata),
                        ),
                    )

                if retained_chunk_ids:
                    self._connection.execute(
                        """
                        DELETE FROM chunks
                        WHERE section_id = %s
                          AND NOT (stable_id = ANY(%s))
                        """,
                        (section_record.id, retained_chunk_ids),
                    )
                else:
                    self._connection.execute(
                        "DELETE FROM chunks WHERE section_id = %s",
                        (section_record.id,),
                    )

            if retained_section_ids:
                self._connection.execute(
                    """
                    DELETE FROM sections
                    WHERE page_id = %s
                      AND NOT (stable_id = ANY(%s))
                    """,
                    (page_id, retained_section_ids),
                )
            else:
                self._connection.execute("DELETE FROM sections WHERE page_id = %s", (page_id,))

            self._connection.execute(
                """
                UPDATE pages
                SET fetch_status = 'parsed',
                    parser_version = %s,
                    parsed_at = now(),
                    indexed_at = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (parser_version, page_id),
            )

    def list_sections_for_page(self, *, page_id: int) -> list[SectionRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM sections
            WHERE page_id = %s
            ORDER BY ordinal, id
            """,
            (page_id,),
        ).fetchall()
        return [_record(SectionRecord, row) for row in rows]

    def get_section_by_id(self, section_id: int) -> SectionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM sections WHERE id = %s",
            (section_id,),
        ).fetchone()
        return _optional_record(SectionRecord, row)

    def get_section_by_stable_id(
        self,
        *,
        page_id: int,
        stable_id: str,
    ) -> SectionRecord | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM sections
            WHERE page_id = %s
              AND stable_id = %s
            """,
            (page_id, stable_id),
        ).fetchone()
        return _optional_record(SectionRecord, row)

    def list_chunks_for_page(self, *, page_id: int) -> list[ChunkRecord]:
        rows = self._connection.execute(
            f"""
            SELECT {CHUNK_CONTENT_COLUMNS}
            FROM chunks
            WHERE page_id = %s
            ORDER BY ordinal, id
            """,
            (page_id,),
        ).fetchall()
        return [_record(ChunkRecord, row) for row in rows]

    def list_chunks_for_section(self, *, section_id: int) -> list[ChunkRecord]:
        rows = self._connection.execute(
            f"""
            SELECT {CHUNK_CONTENT_COLUMNS}
            FROM chunks
            WHERE section_id = %s
            ORDER BY ordinal, id
            """,
            (section_id,),
        ).fetchall()
        return [_record(ChunkRecord, row) for row in rows]

    def refresh_chunk_search_vectors(self, *, doc_version_id: int) -> int:
        cursor = self._connection.execute(
            """
            UPDATE chunks AS c
            SET search_vector =
                    setweight(to_tsvector('english', coalesce(p.title, '')), 'A')
                    || setweight(
                        to_tsvector('english', coalesce(array_to_string(s.section_path, ' '), '')),
                        'A'
                    )
                    || setweight(to_tsvector('english', coalesce(s.heading, '')), 'A')
                    || setweight(to_tsvector('english', coalesce(c.content, '')), 'B'),
                simple_search_vector =
                    setweight(to_tsvector('simple', coalesce(p.title, '')), 'A')
                    || setweight(
                        to_tsvector('simple', coalesce(array_to_string(s.section_path, ' '), '')),
                        'A'
                    )
                    || setweight(to_tsvector('simple', coalesce(s.heading, '')), 'A')
                    || setweight(to_tsvector('simple', coalesce(c.content, '')), 'B'),
                identifier_text = lower(
                    concat_ws(
                        ' ',
                        p.title,
                        p.normalized_path,
                        array_to_string(s.section_path, ' '),
                        s.heading
                    )
                ),
                updated_at = now()
            FROM pages AS p, sections AS s
            WHERE c.page_id = p.id
              AND c.section_id = s.id
              AND p.doc_version_id = %s
            """,
            (doc_version_id,),
        )
        return cursor.rowcount

    def mark_pages_indexed(self, *, doc_version_id: int) -> int:
        cursor = self._connection.execute(
            """
            UPDATE pages AS p
            SET fetch_status = 'indexed',
                indexed_at = now(),
                updated_at = now()
            WHERE p.doc_version_id = %s
              AND p.fetch_status IN ('parsed', 'indexed')
              AND EXISTS (
                SELECT 1
                FROM chunks AS c
                WHERE c.page_id = p.id
                  AND c.search_vector IS NOT NULL
              )
            """,
            (doc_version_id,),
        )
        return cursor.rowcount

    def search_chunks(
        self,
        *,
        doc_version_id: int,
        query: str,
        limit: int = 10,
        book_code: str | None = None,
        page_id: int | None = None,
    ) -> list[SearchResultRecord]:
        search_text = query.strip()
        if not search_text or limit < 1:
            return []

        rows = self._connection.execute(
            """
            WITH search_query AS (
                SELECT websearch_to_tsquery('english', %s) AS query
            )
            SELECT
                dv.code AS version_code,
                dv.label AS version_label,
                b.code AS book_code,
                b.title AS book_title,
                p.id AS page_id,
                p.title AS page_title,
                p.normalized_path AS normalized_path,
                p.source_url AS source_url,
                p.source_metadata AS page_source_metadata,
                s.id AS section_id,
                s.stable_id AS section_stable_id,
                s.heading AS section_heading,
                s.section_path AS section_path,
                c.id AS chunk_id,
                c.stable_id AS chunk_stable_id,
                ts_headline(
                    'english',
                    c.content,
                    search_query.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=8, ShortWord=3'
                ) AS snippet,
                ts_rank_cd(c.search_vector, search_query.query)::float8 AS rank
            FROM chunks AS c
            JOIN pages AS p ON p.id = c.page_id
            JOIN books AS b ON b.id = p.book_id
            JOIN doc_versions AS dv ON dv.id = p.doc_version_id
            JOIN sections AS s ON s.id = c.section_id
            CROSS JOIN search_query
            WHERE p.doc_version_id = %s
              AND (%s::text IS NULL OR b.code = %s)
              AND (%s::bigint IS NULL OR p.id = %s)
              AND c.search_vector @@ search_query.query
            ORDER BY rank DESC, p.id, s.ordinal, c.ordinal, c.id
            LIMIT %s
            """,
            (search_text, doc_version_id, book_code, book_code, page_id, page_id, limit),
        ).fetchall()
        return [_record(SearchResultRecord, row) for row in rows]

    def search_chunks_exact(
        self,
        *,
        doc_version_id: int,
        query: str,
        limit: int = 10,
        book_code: str | None = None,
        page_id: int | None = None,
    ) -> list[SearchResultRecord]:
        search_text = query.strip()
        if not search_text or limit < 1:
            return []

        rows = self._connection.execute(
            """
            WITH exact_query AS (
                SELECT
                    lower(%s) AS query,
                    replace(lower(%s), ' ', '') AS compact_query
            ),
            scored AS (
                SELECT
                    dv.code AS version_code,
                    dv.label AS version_label,
                    b.code AS book_code,
                    b.title AS book_title,
                    p.id AS page_id,
                    p.title AS page_title,
                    p.normalized_path AS normalized_path,
                    p.source_url AS source_url,
                    p.source_metadata AS page_source_metadata,
                    s.id AS section_id,
                    s.stable_id AS section_stable_id,
                    s.heading AS section_heading,
                    s.section_path AS section_path,
                    c.id AS chunk_id,
                    c.stable_id AS chunk_stable_id,
                    regexp_replace(c.content, '\\s+', ' ', 'g') AS clean_content,
                    (
                        CASE
                            WHEN lower(coalesce(p.title, '')) = exact_query.query THEN 100
                            ELSE 0
                        END
                        + CASE
                            WHEN lower(coalesce(s.heading, '')) = exact_query.query THEN 90
                            ELSE 0
                          END
                        + CASE
                            WHEN position(
                                exact_query.query
                                IN lower(coalesce(array_to_string(s.section_path, ' '), ''))
                            ) > 0
                            THEN 40 ELSE 0
                          END
                        + CASE
                            WHEN position(
                                exact_query.compact_query
                                IN lower(coalesce(p.normalized_path, ''))
                            ) > 0
                            THEN 25 ELSE 0
                          END
                        + CASE
                            WHEN position(exact_query.query IN lower(coalesce(c.content, ''))) > 0
                            THEN 10 ELSE 0
                          END
                    )::float8 AS rank
                FROM chunks AS c
                JOIN pages AS p ON p.id = c.page_id
                JOIN books AS b ON b.id = p.book_id
                JOIN doc_versions AS dv ON dv.id = p.doc_version_id
                JOIN sections AS s ON s.id = c.section_id
                CROSS JOIN exact_query
                WHERE p.doc_version_id = %s
                  AND p.fetch_status IN ('parsed', 'indexed')
                  AND (%s::text IS NULL OR b.code = %s)
                  AND (%s::bigint IS NULL OR p.id = %s)
            ),
            ranked AS (
                SELECT
                    scored.*,
                    row_number() OVER (
                        PARTITION BY page_id
                        ORDER BY rank DESC, section_id, chunk_id
                    ) AS page_rank
                FROM scored
            )
            SELECT
                version_code,
                version_label,
                book_code,
                book_title,
                page_id,
                page_title,
                normalized_path,
                source_url,
                page_source_metadata,
                section_id,
                section_stable_id,
                section_heading,
                section_path,
                chunk_id,
                chunk_stable_id,
                CASE
                    WHEN length(clean_content) > 450 THEN left(clean_content, 450) || '...'
                    ELSE clean_content
                END AS snippet,
                rank
            FROM ranked
            WHERE rank > 0
              AND page_rank = 1
            ORDER BY rank DESC, page_id, section_id, chunk_id
            LIMIT %s
            """,
            (
                search_text,
                search_text,
                doc_version_id,
                book_code,
                book_code,
                page_id,
                page_id,
                max(1, min(limit, 50)),
            ),
        ).fetchall()
        return [_record(SearchResultRecord, row) for row in rows]

    def search_chunks_relaxed(
        self,
        *,
        doc_version_id: int,
        query: str,
        limit: int = 10,
        book_code: str | None = None,
        page_id: int | None = None,
    ) -> list[SearchResultRecord]:
        terms = _query_terms(query)
        if not terms or limit < 1:
            return []

        identifier_queries = [term for term in terms if len(term) >= 3]
        candidate_limit = max(100, min(500, limit * 25))
        rows = self._connection.execute(
            """
            WITH search_queries AS (
                SELECT
                    (
                        SELECT string_agg(lexeme, ' | ')::tsquery
                        FROM unnest(
                            tsvector_to_array(to_tsvector('english', %s))
                        ) AS lexeme
                    ) AS english_query,
                    (
                        SELECT string_agg(lexeme, ' | ')::tsquery
                        FROM unnest(
                            tsvector_to_array(to_tsvector('simple', %s))
                        ) AS lexeme
                    ) AS simple_query
            ),
            candidates AS MATERIALIZED (
                SELECT
                    dv.code AS version_code,
                    dv.label AS version_label,
                    b.code AS book_code,
                    b.title AS book_title,
                    p.id AS page_id,
                    p.title AS page_title,
                    p.normalized_path AS normalized_path,
                    p.source_url AS source_url,
                    p.source_metadata AS page_source_metadata,
                    s.id AS section_id,
                    s.stable_id AS section_stable_id,
                    s.heading AS section_heading,
                    s.section_path AS section_path,
                    c.id AS chunk_id,
                    c.stable_id AS chunk_stable_id,
                    regexp_replace(c.content, '\\s+', ' ', 'g') AS clean_content,
                    c.simple_search_vector,
                    c.identifier_text,
                    coalesce(ts_rank_cd(c.search_vector, sq.english_query), 0)::float8
                        AS english_rank,
                    coalesce(ts_rank_cd(c.simple_search_vector, sq.simple_query), 0)::float8
                        AS simple_rank,
                    coalesce((
                        SELECT max(word_similarity(identifier_query, c.identifier_text))
                        FROM unnest(%s::text[]) AS identifier_query
                    ), 0)::float8 AS identifier_rank
                FROM chunks AS c
                JOIN pages AS p ON p.id = c.page_id
                JOIN books AS b ON b.id = p.book_id
                JOIN doc_versions AS dv ON dv.id = p.doc_version_id
                JOIN sections AS s ON s.id = c.section_id
                CROSS JOIN search_queries AS sq
                WHERE p.doc_version_id = %s
                  AND p.fetch_status IN ('parsed', 'indexed')
                  AND (%s::text IS NULL OR b.code = %s)
                  AND (%s::bigint IS NULL OR p.id = %s)
                  AND (
                      c.search_vector @@ sq.english_query
                      OR c.simple_search_vector @@ sq.simple_query
                      OR c.identifier_text %%> ANY(%s::text[])
                  )
                ORDER BY
                    coalesce(ts_rank_cd(c.search_vector, sq.english_query), 0) DESC,
                    coalesce(ts_rank_cd(c.simple_search_vector, sq.simple_query), 0) DESC,
                    identifier_rank DESC,
                    c.id
                LIMIT %s
            ),
            scored AS (
                SELECT
                    candidates.*,
                    coverage.matched_terms,
                    positions.snippet_match_position,
                    (
                        coverage.matched_terms * 100.0
                        + english_rank * 20.0
                        + simple_rank * 10.0
                        + identifier_rank * 5.0
                    )::float8 AS rank
                FROM candidates
                CROSS JOIN LATERAL (
                    SELECT count(*)::int AS matched_terms
                    FROM unnest(%s::text[]) AS query_term
                    WHERE candidates.simple_search_vector
                        @@ plainto_tsquery('simple', query_term)
                        OR candidates.identifier_text %%> query_term
                ) AS coverage
                CROSS JOIN LATERAL (
                    SELECT max(NULLIF(strpos(lower(candidates.clean_content), query_term), 0))
                        AS snippet_match_position
                    FROM unnest(%s::text[]) AS query_term
                ) AS positions
            ),
            diversified AS (
                SELECT
                    scored.*,
                    row_number() OVER (
                        PARTITION BY page_id
                        ORDER BY matched_terms DESC, rank DESC, section_id, chunk_id
                    ) AS page_rank
                FROM scored
            )
            SELECT
                version_code,
                version_label,
                book_code,
                book_title,
                page_id,
                page_title,
                normalized_path,
                source_url,
                page_source_metadata,
                section_id,
                section_stable_id,
                section_heading,
                section_path,
                chunk_id,
                chunk_stable_id,
                CASE
                    WHEN snippet_match_position IS NOT NULL
                         AND snippet_match_position > 180
                    THEN
                        '...'
                        || substring(clean_content FROM snippet_match_position - 180 FOR 450)
                        || CASE
                            WHEN length(clean_content) > snippet_match_position + 270
                            THEN '...'
                            ELSE ''
                        END
                    WHEN length(clean_content) > 450 THEN left(clean_content, 450) || '...'
                    ELSE clean_content
                END AS snippet,
                rank
            FROM diversified
            WHERE matched_terms >= %s
              AND page_rank = 1
            ORDER BY matched_terms DESC, rank DESC, page_id, section_id, chunk_id
            LIMIT %s
            """,
            (
                query,
                query,
                identifier_queries,
                doc_version_id,
                book_code,
                book_code,
                page_id,
                page_id,
                identifier_queries,
                candidate_limit,
                terms,
                terms,
                _minimum_relaxed_matches(len(terms)),
                max(1, min(limit, 50)),
            ),
        ).fetchall()
        return [_record(SearchResultRecord, row) for row in rows]

    def _find_page_by_unique_key(
        self,
        *,
        doc_version_id: int,
        normalized_url: str,
        normalized_path: str,
    ) -> PageRecord | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM pages
            WHERE doc_version_id = %s
              AND (normalized_url = %s OR normalized_path = %s)
            ORDER BY id
            LIMIT 1
            """,
            (doc_version_id, normalized_url, normalized_path),
        ).fetchone()
        return _optional_record(PageRecord, row)

    def _refresh_page_discovery(
        self,
        *,
        page_id: int,
        book_id: int,
        nav_node_id: int | None,
        source_url: str,
        title: str | None,
        source_metadata: JsonObject | None,
    ) -> PageRecord:
        row = self._connection.execute(
            """
            UPDATE pages
            SET book_id = CASE WHEN %s IS NULL THEN book_id ELSE %s END,
                nav_node_id = COALESCE(%s, nav_node_id),
                source_url = %s,
                title = COALESCE(%s, title),
                source_metadata = source_metadata || %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                nav_node_id,
                book_id,
                nav_node_id,
                source_url,
                title,
                Jsonb(source_metadata or {}),
                page_id,
            ),
        ).fetchone()
        return _record(PageRecord, row)


def _record[T](record_type: type[T], row: JsonObject | None) -> T:
    if row is None:
        raise LookupError(f"Expected {record_type.__name__} row")
    return record_type(**row)


def _optional_record[T](record_type: type[T], row: JsonObject | None) -> T | None:
    if row is None:
        return None
    return _record(record_type, row)


def _query_terms(query: str, *, max_terms: int = 16) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in QUERY_TERM_RE.finditer(query.lower()):
        term = match.group(0).strip("'_-")
        if len(term) < 2 or term in QUERY_STOP_WORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def _minimum_relaxed_matches(term_count: int) -> int:
    if term_count <= 1:
        return 1
    if term_count <= 4:
        return 2
    return max(2, min(6, math.ceil(term_count * 0.3)))


def _path_stem(path: str) -> str:
    leaf = path.rstrip("/").rsplit("/", 1)[-1].lower()
    if leaf.endswith(".html"):
        leaf = leaf[:-5]
    return leaf
