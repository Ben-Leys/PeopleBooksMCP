from __future__ import annotations

import psycopg
import pytest

from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.repositories import ChunkInput, PeopleBooksRepository, SectionInput


def test_repository_upserts_seed_data_and_queues_unique_pages(postgres_url: str) -> None:
    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        same_version = repository.upsert_doc_version(
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
        nav_node = repository.upsert_nav_node(
            doc_version_id=version.id,
            book_id=book.id,
            parent_id=None,
            stable_id="tpcr/root",
            title="PeopleCode API Reference",
            node_type="book",
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home",
            position=0,
            source_metadata={"focusnode": "home"},
        )
        page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            nav_node_id=nav_node.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html?ctx=api",
            title="A PeopleCode Class",
            source_metadata={"focusnode": "a"},
        )
        same_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            nav_node_id=nav_node.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/a.html?ctx=api",
            title="A PeopleCode Class",
            source_metadata={"focusnode": "a"},
        )

        assert same_version.id == version.id
        assert same_page.id == page.id
        assert page.fetch_status == "queued"
        assert repository.list_next_queued_pages(doc_version_id=version.id, limit=5) == [same_page]


def test_repository_refreshes_existing_page_discovery_metadata(postgres_url: str) -> None:
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
        initial_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            title=None,
            source_metadata={},
        )
        nav_node = repository.upsert_nav_node(
            doc_version_id=version.id,
            book_id=book.id,
            parent_id=None,
            stable_id="tpcr/b",
            title="B PeopleCode Class",
            node_type="page",
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html?focusnode=b",
            position=3,
            source_metadata={"focusnode": "b"},
        )
        refreshed_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            nav_node_id=nav_node.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/b.html?focusnode=b",
            title="B PeopleCode Class",
            source_metadata={"focusnode": "b"},
        )

        assert refreshed_page.id == initial_page.id
        assert refreshed_page.nav_node_id == nav_node.id
        assert refreshed_page.title == "B PeopleCode Class"
        assert refreshed_page.source_url.endswith("?focusnode=b")
        assert refreshed_page.source_metadata == {"focusnode": "b"}


def test_repository_records_fetch_result_atomically_without_parser_version(
    postgres_url: str,
) -> None:
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
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/d.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/d.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/d.html",
            title="D PeopleCode Class",
            source_metadata={},
        )

        fetched_page, event = repository.record_fetch_success(
            page_id=page.id,
            raw_html="<html><h1>B PeopleCode Class</h1></html>",
            content_hash="sha256:abc123",
            status_code=200,
            elapsed_ms=42,
            source_url=page.source_url,
            source_metadata={"content_type": "text/html"},
            metadata={"attempt": 1},
        )

        assert fetched_page.fetch_status == "fetched"
        assert fetched_page.raw_html == "<html><h1>B PeopleCode Class</h1></html>"
        assert fetched_page.content_hash == "sha256:abc123"
        assert fetched_page.parser_version is None
        assert event.fetch_status == "fetched"
        assert event.content_hash == "sha256:abc123"
        assert repository.list_fetch_events(page_id=page.id) == [event]


def test_repository_replaces_parsed_sections_and_chunks(postgres_url: str) -> None:
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
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/c.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/c.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/c.html",
            title="CreateArray",
            source_metadata={},
        )

        repository.replace_page_sections(
            page_id=page.id,
            parser_version="parser-v1",
            sections=[
                SectionInput(
                    stable_id="createarray",
                    heading="CreateArray",
                    level=1,
                    section_path=("CreateArray",),
                    ordinal=0,
                    content="CreateArray creates a new array.",
                    chunks=[
                        ChunkInput(
                            stable_id="createarray-0",
                            ordinal=0,
                            content="CreateArray creates a new array.",
                            metadata={"kind": "summary"},
                        )
                    ],
                    source_metadata={"tag": "h1"},
                )
            ],
        )
        repository.replace_page_sections(
            page_id=page.id,
            parser_version="parser-v2",
            sections=[
                SectionInput(
                    stable_id="createarray",
                    heading="CreateArray",
                    level=1,
                    section_path=("CreateArray",),
                    ordinal=0,
                    content="CreateArray returns an array object.",
                    chunks=[
                        ChunkInput(
                            stable_id="createarray-0",
                            ordinal=0,
                            content="CreateArray returns an array object.",
                            metadata={"kind": "summary"},
                        ),
                        ChunkInput(
                            stable_id="createarray-1",
                            ordinal=1,
                            content="Use it when array length is not known in advance.",
                            metadata={"kind": "usage"},
                        ),
                    ],
                    source_metadata={"tag": "h1"},
                )
            ],
        )

        sections = repository.list_sections_for_page(page_id=page.id)
        chunks = repository.list_chunks_for_page(page_id=page.id)

        assert len(sections) == 1
        assert sections[0].parser_version == "parser-v2"
        assert sections[0].content == "CreateArray returns an array object."
        assert [chunk.stable_id for chunk in chunks] == ["createarray-0", "createarray-1"]


def test_schema_rejects_chunk_with_mismatched_page_and_section(postgres_url: str) -> None:
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
        first_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/e.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/e.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/e.html",
            title="First Page",
            source_metadata={},
        )
        second_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/f.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/f.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/f.html",
            title="Second Page",
            source_metadata={},
        )
        repository.replace_page_sections(
            page_id=first_page.id,
            parser_version="parser-v1",
            sections=[
                SectionInput(
                    stable_id="first",
                    heading="First",
                    level=1,
                    section_path=("First",),
                    ordinal=0,
                    content="First section.",
                    chunks=[],
                    source_metadata={},
                )
            ],
        )
        section = repository.list_sections_for_page(page_id=first_page.id)[0]

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.connection.execute(
                """
                INSERT INTO chunks (page_id, section_id, stable_id, ordinal, content)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (second_page.id, section.id, "bad-chunk", 0, "Wrong page."),
            )
