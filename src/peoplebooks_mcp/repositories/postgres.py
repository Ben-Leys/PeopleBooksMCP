from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from peoplebooks_mcp.database import connect

JsonObject = dict[str, Any]


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
    section_id: int
    section_stable_id: str
    section_heading: str
    section_path: list[str]
    chunk_id: int
    chunk_stable_id: str
    snippet: str
    rank: float


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
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = dict_row

    @classmethod
    @contextmanager
    def connect(cls, database_url: str) -> Iterator[Self]:
        with connect(database_url) as connection:
            yield cls(connection)

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
            self._connection.execute("DELETE FROM sections WHERE page_id = %s", (page_id,))

            for section in sections:
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

                for chunk in section.chunks:
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

    def list_chunks_for_page(self, *, page_id: int) -> list[ChunkRecord]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM chunks
            WHERE page_id = %s
            ORDER BY ordinal, id
            """,
            (page_id,),
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
              AND c.search_vector @@ search_query.query
            ORDER BY rank DESC, p.id, s.ordinal, c.ordinal, c.id
            LIMIT %s
            """,
            (search_text, doc_version_id, limit),
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
