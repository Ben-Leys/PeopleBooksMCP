from __future__ import annotations

import psycopg
import pytest

from peoplebooks_mcp.database import run_migrations
from tests.postgres_test_utils import column_names, constraint_names, index_names, table_names


def test_migrations_create_phase_2_tables_and_columns(postgres_url: str) -> None:
    run_migrations(postgres_url)

    assert {
        "doc_versions",
        "books",
        "nav_nodes",
        "pages",
        "sections",
        "chunks",
        "fetch_events",
    }.issubset(table_names(postgres_url))

    assert {
        "doc_version_id",
        "normalized_url",
        "normalized_path",
        "source_url",
        "source_metadata",
        "raw_html",
        "content_hash",
        "parser_version",
        "fetch_status",
        "queued_at",
        "fetched_at",
        "parsed_at",
        "created_at",
        "updated_at",
    }.issubset(column_names(postgres_url, "pages"))

    page_constraints = constraint_names(postgres_url, "pages")
    assert "uq_pages_doc_version_normalized_url" in page_constraints
    assert "uq_pages_doc_version_normalized_path" in page_constraints


def test_migrations_create_phase_5_chunk_search_vector_and_index(postgres_url: str) -> None:
    run_migrations(postgres_url)

    assert "search_vector" in column_names(postgres_url, "chunks")
    assert "ix_chunks_search_vector" in index_names(postgres_url, "chunks")
    assert "simple_search_vector" in column_names(postgres_url, "chunks")
    assert "identifier_text" in column_names(postgres_url, "chunks")
    assert "ix_chunks_simple_search_vector" in index_names(postgres_url, "chunks")
    assert "ix_chunks_identifier_text_trgm" in index_names(postgres_url, "chunks")


def test_fetch_events_are_append_only(postgres_url: str) -> None:
    from peoplebooks_mcp.repositories import PeopleBooksRepository

    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            title="A PeopleCode Class",
            source_metadata={"focusnode": "a"},
        )
        event = repository.record_fetch_event(
            page_id=page.id,
            event_type="fetch_failed",
            fetch_status="failed",
            status_code=503,
            error_message="Service Unavailable",
            elapsed_ms=120,
            content_hash=None,
            source_url=page.source_url,
            metadata={"attempt": 1},
        )

        with pytest.raises(Exception, match="fetch_events rows are append-only"):
            repository.connection.execute(
                "UPDATE fetch_events SET event_type = 'changed' WHERE id = %s",
                (event.id,),
            )

        with pytest.raises(Exception, match="fetch_events rows are append-only"):
            repository.connection.execute("DELETE FROM fetch_events WHERE id = %s", (event.id,))

        with pytest.raises(Exception, match="fetch_events rows are append-only"):
            repository.connection.execute("TRUNCATE fetch_events")


def test_schema_rejects_cross_version_page_relationships(postgres_url: str) -> None:
    from peoplebooks_mcp.repositories import PeopleBooksRepository

    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        pt862 = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        pt861 = repository.upsert_doc_version(
            code="pt861",
            label="PeopleTools 8.61",
            seed_url="https://docs.oracle.com/cd/example/pt861/index.html",
        )
        repository.upsert_book(
            doc_version_id=pt862.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        other_book = repository.upsert_book(
            doc_version_id=pt861.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url="https://docs.oracle.com/cd/example/pt861/index.html",
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.queue_page(
                doc_version_id=pt862.id,
                book_id=other_book.id,
                normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/x.html",
                normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/x.html",
                source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/x.html",
                title="Mismatched Page",
                source_metadata={},
            )


def test_schema_rejects_cross_book_nav_parent_relationships(postgres_url: str) -> None:
    from peoplebooks_mcp.repositories import PeopleBooksRepository

    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        peoplecode_book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        tools_book = repository.upsert_book(
            doc_version_id=version.id,
            code="tprt",
            title="PeopleTools Runtime Reference",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        parent = repository.upsert_nav_node(
            doc_version_id=version.id,
            book_id=peoplecode_book.id,
            parent_id=None,
            stable_id="tpcr/root",
            title="PeopleCode API Reference",
            node_type="book",
            normalized_url=None,
            source_url=None,
            position=0,
            source_metadata={},
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.upsert_nav_node(
                doc_version_id=version.id,
                book_id=tools_book.id,
                parent_id=parent.id,
                stable_id="tprt/bad-child",
                title="Bad Child",
                node_type="page",
                normalized_url=None,
                source_url=None,
                position=0,
                source_metadata={},
            )
