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
    assert "source_metadata" not in books["books"][0]
    assert "created_at" not in books["books"][0]

    assert search["results"][0]["version"]["code"] == "pt862"
    assert search["results"][0]["book"]["code"] == "tpcr"
    assert search["results"][0]["page"]["page_id"] == ids["page_id"]
    assert search["results"][0]["page"]["source_url"].endswith("/createarray.html")
    assert search["results"][0]["section"]["stable_id"] == "createarray"
    assert search["results"][0]["chunk"]["stable_id"] == "createarray-0"
    assert "source_metadata" not in search["results"][0]["page"]

    assert page["page"]["id"] == ids["page_id"]
    assert page["page"]["normalized_path"].endswith("/createarray.html")
    assert page["sections"][0]["stable_id"] == "createarray"
    assert "content" not in page["sections"][0]
    assert "chunks" not in page["sections"][0]
    assert "source_metadata" not in page["page"]

    assert section["section"]["id"] == ids["section_id"]
    assert section["section"]["stable_id"] == "createarray"
    assert section["chunks"][0]["stable_id"] == "createarray-0"
    assert "source_metadata" not in section["section"]


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
    assert "source_metadata" not in versions["versions"][0]
    assert "source_metadata" not in version["version"]
    assert books["books"][0]["code"] == "tpcr"
    assert pages["pages"][0]["id"] == ids["page_id"]
    assert pages["pages"][0]["title"] == "CreateArray"
    assert page["sections"][0]["stable_id"] == "createarray"
    assert "source_metadata" not in page["sections"][0]
    assert "chunks" not in page["sections"][0]
    assert section["section"]["stable_id"] == "createarray"
    assert "source_metadata" not in section["section"]


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


def test_mcp_health_reports_ready_schema_and_index_counts(postgres_url: str) -> None:
    run_migrations(postgres_url)
    _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(server, "health", {"version": "pt862"})

    assert result["status"] == "ready"
    assert result["schema"]["current_revision"] == "0002_phase_5_full_text_indexing"
    assert result["schema"]["is_current"] is True
    assert result["schema"]["missing_required_columns"] == []
    assert result["content"]["parsed_pages"] == 4
    assert result["content"]["indexed_chunks"] == 4


def test_mcp_health_reports_degraded_when_index_is_partial(postgres_url: str) -> None:
    run_migrations(postgres_url)
    _seed_agent_workflow_docs(postgres_url, index=False)
    server = create_server(database_url=postgres_url)

    result = _call_tool(server, "health", {"version": "pt862"})

    assert result["status"] == "degraded"
    assert result["content"]["total_chunks"] == 4
    assert result["content"]["indexed_chunks"] == 0
    assert result["content"]["partial_index"] is True


def test_mcp_find_pages_returns_bounded_thin_candidates(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "find_pages",
        {
            "version": "pt862",
            "query": "Application Engine state records",
            "book_code": "tape",
            "limit": 2,
        },
    )

    assert result["query"] == "Application Engine state records"
    assert result["book_code"] == "tape"
    assert len(result["pages"]) <= 2
    assert result["pages"][0]["page_id"] == ids["state_records_page_id"]
    assert result["pages"][0]["title"] == "Using State Records"
    assert result["pages"][0]["book"]["code"] == "tape"
    assert "id" not in result["pages"][0]
    assert "fetch_status" not in result["pages"][0]
    assert "sections" not in result["pages"][0]
    assert "chunks" not in result["pages"][0]
    assert "content" not in result["pages"][0]


def test_mcp_get_page_outline_returns_headings_without_content(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "get_page_outline",
        {"version": "pt862", "page_id": ids["program_elements_page_id"]},
    )

    assert result["page"]["title"] == "Application Engine Program Elements"
    assert result["section_count"] == 2
    assert result["next_offset"] is None
    assert [section["heading"] for section in result["sections"]] == [
        "Application Engine Program Elements",
        "Sections, Steps, and Actions",
    ]
    assert "content" not in result["sections"][0]
    assert "chunks" not in result["sections"][0]
    assert "source_metadata" not in result["sections"][0]
    assert "section_path" not in result["sections"][0]


def test_mcp_get_page_outline_can_page_and_filter_heading_levels(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    first_page = _call_tool(
        server,
        "get_page_outline",
        {
            "version": "pt862",
            "page_id": ids["program_elements_page_id"],
            "limit": 1,
            "offset": 0,
        },
    )
    h1_only = _call_tool(
        server,
        "get_page_outline",
        {
            "version": "pt862",
            "page_id": ids["program_elements_page_id"],
            "max_level": 1,
        },
    )

    assert first_page["section_count"] == 2
    assert first_page["returned_count"] == 1
    assert first_page["next_offset"] == 1
    assert [section["heading"] for section in first_page["sections"]] == [
        "Application Engine Program Elements",
    ]
    assert h1_only["section_count"] == 1
    assert [section["level"] for section in h1_only["sections"]] == [1]


def test_mcp_get_page_returns_paged_compact_headings(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "get_page",
        {
            "version": "pt862",
            "page_id": ids["program_elements_page_id"],
            "limit": 1,
        },
    )

    assert result["section_count"] == 2
    assert result["returned_count"] == 1
    assert result["next_offset"] == 1
    assert [section["heading"] for section in result["sections"]] == [
        "Application Engine Program Elements",
    ]
    assert "content" not in result["sections"][0]
    assert "chunks" not in result["sections"][0]


def test_mcp_search_docs_uses_relaxed_fallback_for_over_specific_queries(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "book_code": "tape",
            "query": (
                "Application Engine what is Application Engine program use cases "
                "properties state records sections steps actions PeopleTools"
            ),
            "limit": 5,
        },
    )

    assert result["match_mode"] == "relaxed"
    assert result["results"][0]["page"]["page_id"] == ids["state_records_page_id"]
    assert result["results"][0]["book"]["code"] == "tape"
    assert "state records" in result["results"][0]["chunk"]["snippet"].lower()


def test_mcp_search_docs_page_id_filter_scopes_results(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "Application Engine",
            "page_id": ids["overview_page_id"],
            "limit": 5,
        },
    )

    assert result["match_mode"] == "strict"
    assert result["filters"]["page_id"] == ids["overview_page_id"]
    assert {item["page"]["page_id"] for item in result["results"]} == {ids["overview_page_id"]}


def test_mcp_search_docs_relaxed_snippet_is_near_matched_terms(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "book_code": "tape",
            "query": "Application Engine rare tail marker impossiblemissingterm",
            "limit": 5,
        },
    )

    assert result["match_mode"] == "relaxed"
    assert result["results"][0]["page"]["page_id"] == ids["long_tail_page_id"]
    snippet = result["results"][0]["chunk"]["snippet"].lower()
    assert "rare tail marker" in snippet
    assert len(snippet) < 520


def test_mcp_get_page_unknown_path_returns_structured_suggestions(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "get_page",
        {"version": "pt862", "normalized_path": "tape.html"},
    )

    assert result["error"]["code"] == "page_not_found"
    assert result["error"]["path"] == "tape.html"
    assert result["suggestions"][0]["page_id"] == ids["overview_page_id"]
    assert result["suggestions"][0]["book"]["code"] == "tape"
    assert "id" not in result["suggestions"][0]
    assert "content" not in result["suggestions"][0]


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


def _seed_agent_workflow_docs(database_url: str, *, index: bool = True) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
            source_metadata={"doc_set": "pt862pbr3"},
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tape",
            title="Application Engine",
            seed_url=version.seed_url,
            source_metadata={"doc_set": "pt862pbr3"},
        )
        overview_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="ApplicationEngineOverview",
            title="Application Engine Overview",
            sections=[
                SectionInput(
                    stable_id="application-engine-overview",
                    heading="Application Engine Overview",
                    level=1,
                    section_path=("Application Engine Overview",),
                    ordinal=0,
                    content="Application Engine runs background SQL and PeopleCode programs.",
                    chunks=[
                        ChunkInput(
                            stable_id="application-engine-overview-0",
                            ordinal=0,
                            content=(
                                "Application Engine runs background SQL and PeopleCode programs."
                            ),
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        state_records_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="UsingStateRecords-077213",
            title="Using State Records",
            sections=[
                SectionInput(
                    stable_id="understanding-state-records",
                    heading="Understanding State Records",
                    level=1,
                    section_path=("Using State Records", "Understanding State Records"),
                    ordinal=0,
                    content=(
                        "State records pass values through an Application Engine program. "
                        "They are available to sections, steps, and actions."
                    ),
                    chunks=[
                        ChunkInput(
                            stable_id="understanding-state-records-0",
                            ordinal=0,
                            content=(
                                "State records pass values through an Application Engine program. "
                                "They are available to sections, steps, and actions."
                            ),
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        program_elements_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="ApplicationEngineProgramElements-07725e",
            title="Application Engine Program Elements",
            sections=[
                SectionInput(
                    stable_id="application-engine-program-elements",
                    heading="Application Engine Program Elements",
                    level=1,
                    section_path=("Application Engine Program Elements",),
                    ordinal=0,
                    content="Application Engine programs contain sections, steps, and actions.",
                    chunks=[
                        ChunkInput(
                            stable_id="application-engine-program-elements-0",
                            ordinal=0,
                            content=(
                                "Application Engine programs contain sections, steps, and actions."
                            ),
                            metadata={},
                        )
                    ],
                    source_metadata={},
                ),
                SectionInput(
                    stable_id="sections-steps-actions",
                    heading="Sections, Steps, and Actions",
                    level=2,
                    section_path=(
                        "Application Engine Program Elements",
                        "Sections, Steps, and Actions",
                    ),
                    ordinal=1,
                    content=(
                        "A section contains ordered steps. Each step contains one or more actions."
                    ),
                    chunks=[],
                    source_metadata={},
                ),
            ],
        )
        long_tail_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="LongTailSearchExample",
            title="Long Tail Search Example",
            sections=[
                SectionInput(
                    stable_id="long-tail-search-example",
                    heading="Long Tail Search Example",
                    level=1,
                    section_path=("Long Tail Search Example",),
                    ordinal=0,
                    content=(
                        "Application Engine introduction. "
                        + ("filler words " * 80)
                        + "The rare tail marker describes a precise retrieval target."
                    ),
                    chunks=[
                        ChunkInput(
                            stable_id="long-tail-search-example-0",
                            ordinal=0,
                            content=(
                                "Application Engine introduction. "
                                + ("filler words " * 80)
                                + "The rare tail marker describes a precise retrieval target."
                            ),
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        if index:
            index_pages(repository=repository, version_code="pt862")

    return {
        "overview_page_id": overview_page.id,
        "state_records_page_id": state_records_page.id,
        "program_elements_page_id": program_elements_page.id,
        "long_tail_page_id": long_tail_page.id,
    }


def _queue_page_with_sections(
    *,
    repository: PeopleBooksRepository,
    doc_version_id: int,
    book_id: int,
    slug: str,
    title: str,
    sections: list[SectionInput],
):
    page = repository.queue_page(
        doc_version_id=doc_version_id,
        book_id=book_id,
        normalized_url=f"https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tape/{slug}.html",
        normalized_path=f"/cd/G41075_01/pt862pbr3/eng/pt/tape/{slug}.html",
        source_url=f"https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tape/{slug}.html",
        title=title,
        source_metadata={"oracle_book": "tape"},
    )
    repository.replace_page_sections(
        page_id=page.id,
        parser_version="parser-v1",
        sections=sections,
    )
    return page
