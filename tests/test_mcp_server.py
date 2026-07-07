from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any

from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.indexing import index_pages
from peoplebooks_mcp.mcp_server import create_server
from peoplebooks_mcp.repositories import ChunkInput, PeopleBooksRepository, SectionInput


def test_mcp_tools_return_indexed_docs_with_stable_ids(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_indexed_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    books = _call_tool(server, "list_books", {"version": "pt862"})
    search = _call_tool(server, "search_docs", {"version": "pt862", "query": "array object"})
    page = _call_tool(server, "get_page", {"version": "pt862", "page_id": ids["page_id"]})
    section = _call_tool(
        server,
        "get_section",
        {"version": "pt862", "section_id": ids["section_id"]},
    )

    assert books["version"]["code"] == "pt862"
    assert books["books"][0]["code"] == "tpcr"
    assert books["books"][0]["source_metadata"]["doc_set"] == "pt862pbr3"

    assert search["results"][0]["version"]["code"] == "pt862"
    assert search["results"][0]["book"]["code"] == "tpcr"
    assert search["results"][0]["page"]["id"] == ids["page_id"]
    assert search["results"][0]["page"]["source_url"].endswith("/createarray.html")
    assert search["results"][0]["page"]["source_metadata"]["oracle_book"] == "tpcr"
    assert search["results"][0]["section"]["stable_id"] == "createarray"
    assert search["results"][0]["chunk"]["stable_id"] == "createarray-0"

    assert page["page"]["id"] == ids["page_id"]
    assert page["page"]["normalized_path"].endswith("/createarray.html")
    assert page["sections"][0]["stable_id"] == "createarray"
    assert page["sections"][0]["chunks"][0]["stable_id"] == "createarray-0"
    assert page["page"]["source_metadata"]["oracle_book"] == "tpcr"

    assert section["section"]["id"] == ids["section_id"]
    assert section["section"]["stable_id"] == "createarray"
    assert section["section"]["source_metadata"]["anchor"] == "createarray"
    assert section["chunks"][0]["stable_id"] == "createarray-0"


def test_mcp_resources_expose_versions_books_pages_and_sections(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_indexed_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    versions = _read_json_resource(server, "peoplebooks://versions")
    version = _read_json_resource(server, "peoplebooks://versions/pt862")
    books = _read_json_resource(server, "peoplebooks://versions/pt862/books")
    pages = _read_json_resource(server, "peoplebooks://versions/pt862/books/tpcr/pages")
    page = _read_json_resource(server, f"peoplebooks://pages/{ids['page_id']}")
    section = _read_json_resource(server, f"peoplebooks://sections/{ids['section_id']}")

    assert versions["versions"][0]["code"] == "pt862"
    assert versions["versions"][0]["source_metadata"]["doc_set"] == "pt862pbr3"
    assert version["version"]["source_metadata"]["doc_set"] == "pt862pbr3"
    assert books["books"][0]["code"] == "tpcr"
    assert books["books"][0]["source_metadata"]["doc_set"] == "pt862pbr3"
    assert pages["pages"][0]["id"] == ids["page_id"]
    assert pages["pages"][0]["title"] == "CreateArray"
    assert pages["pages"][0]["source_metadata"]["oracle_book"] == "tpcr"
    assert page["page"]["source_metadata"]["oracle_book"] == "tpcr"
    assert page["sections"][0]["stable_id"] == "createarray"
    assert page["sections"][0]["source_metadata"]["anchor"] == "createarray"
    assert section["section"]["stable_id"] == "createarray"
    assert section["section"]["source_metadata"]["anchor"] == "createarray"


def test_mcp_tool_can_get_section_by_page_path_and_stable_id(postgres_url: str) -> None:
    run_migrations(postgres_url)
    _seed_indexed_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "get_section",
        {
            "version": "pt862",
            "normalized_path": "/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            "section_stable_id": "createarray",
        },
    )

    assert result["section"]["heading"] == "CreateArray"
    assert result["page"]["title"] == "CreateArray"
    assert result["chunks"][0]["stable_id"] == "createarray-0"


def _run[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def _call_tool(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _content, structured_content = _run(server.call_tool(name, arguments))
    return structured_content


def _read_json_resource(server: Any, uri: str) -> dict[str, Any]:
    contents = _run(server.read_resource(uri))
    return json.loads(contents[0].content)


def _seed_indexed_docs(database_url: str) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
            source_metadata={"doc_set": "pt862pbr3"},
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
            source_metadata={"doc_set": "pt862pbr3"},
        )
        page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            title="CreateArray",
            source_metadata={"oracle_book": "tpcr"},
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
                    content="CreateArray returns an array object for PeopleCode programs.",
                    chunks=[
                        ChunkInput(
                            stable_id="createarray-0",
                            ordinal=0,
                            content="CreateArray returns an array object for PeopleCode programs.",
                            metadata={"kind": "summary"},
                        )
                    ],
                    source_metadata={"anchor": "createarray"},
                )
            ],
        )
        section = repository.list_sections_for_page(page_id=page.id)[0]
        index_pages(repository=repository, version_code="pt862")

    return {"page_id": page.id, "section_id": section.id}
