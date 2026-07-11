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

    assert "version" not in search["results"][0]
    assert search["results"][0]["book"]["code"] == "tpcr"
    assert search["results"][0]["page"]["page_id"] == ids["page_id"]
    assert search["results"][0]["page"]["source_url"].endswith("/createarray.html")
    assert search["results"][0]["section"]["stable_id"] == "createarray"
    assert set(search["results"][0]["chunk"]) == {"snippet"}
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


def test_mcp_structured_tools_do_not_duplicate_json_as_text_content(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    ids = _seed_indexed_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    search_result = _run(
        server.call_tool("search_docs", {"version": "pt862", "query": "array object"})
    )
    section_result = _run(
        server.call_tool("get_section", {"version": "pt862", "section_id": ids["section_id"]})
    )

    for result in [search_result, section_result]:
        assert not isinstance(result, tuple)
        assert result.content == []
        assert result.structuredContent


def test_mcp_search_docs_returns_lean_markup_free_results(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_indexed_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "array object",
            "page_id": ids["page_id"],
            "max_chars": 120,
        },
    )

    assert "query" not in result
    assert "filters" not in result
    assert "id" not in result["version"]
    assert set(result["budget"]) == {"truncated"}

    item = result["results"][0]
    assert "version" not in item
    assert "normalized_path" not in item["page"]
    assert set(item["chunk"]) == {"snippet"}
    assert "<mark>" not in item["chunk"]["snippet"]
    assert "</mark>" not in item["chunk"]["snippet"]


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


def test_mcp_get_section_defaults_to_compact_budget_and_full_detail_is_opt_in(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    ids = _seed_long_section_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    compact = _call_tool(
        server,
        "get_section",
        {"version": "pt862", "section_id": ids["section_id"], "max_chars": 90},
    )
    full = _call_tool(
        server,
        "get_section",
        {
            "version": "pt862",
            "section_id": ids["section_id"],
            "detail": "full",
            "max_chars": 500,
        },
    )

    assert "content" not in compact["section"]
    assert "content" not in compact["chunks"][0]
    assert compact["chunks"][0]["snippet"].endswith("...")
    assert len(compact["chunks"][0]["snippet"]) <= 93
    assert compact["budget"]["truncated"] is True

    assert full["section"]["content"].startswith("Application classes can expose")
    assert full["chunks"][0]["content"].startswith("Application classes can expose")
    assert full["budget"]["truncated"] is False


def test_mcp_tools_and_resources_never_expose_raw_html(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_long_section_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    payloads = [
        _call_tool(server, "list_books", {"version": "pt862"}),
        _call_tool(server, "search_docs", {"version": "pt862", "query": "application class"}),
        _call_tool(server, "find_pages", {"version": "pt862", "query": "application class"}),
        _call_tool(server, "get_page", {"version": "pt862", "page_id": ids["page_id"]}),
        _call_tool(server, "get_page_outline", {"version": "pt862", "page_id": ids["page_id"]}),
        _call_tool(server, "get_section", {"version": "pt862", "section_id": ids["section_id"]}),
        _call_tool(server, "health", {"version": "pt862"}),
        _read_json_resource(server, "peoplebooks://versions"),
        _read_json_resource(server, "peoplebooks://versions/pt862"),
        _read_json_resource(server, "peoplebooks://versions/pt862/books"),
        _read_json_resource(server, "peoplebooks://versions/pt862/books/tpcr/pages"),
        _read_json_resource(server, f"peoplebooks://pages/{ids['page_id']}"),
        _read_json_resource(server, f"peoplebooks://sections/{ids['section_id']}"),
    ]

    for payload in payloads:
        assert "raw_html" not in _json_keys(payload)


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
    assert {item["page"]["page_id"] for item in result["results"]} == {ids["overview_page_id"]}


def test_mcp_search_docs_respects_snippet_budget(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_agent_workflow_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "Application Engine rare tail marker",
            "page_id": ids["long_tail_page_id"],
            "max_chars": 80,
        },
    )

    snippet = result["results"][0]["chunk"]["snippet"]
    assert len(snippet) <= 83
    assert result["budget"]["truncated"] is True


def test_mcp_search_docs_budget_applies_across_all_returned_snippets(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    _seed_many_search_result_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "BudgetTerm",
            "limit": 5,
            "max_chars": 120,
        },
    )

    snippets = [item["chunk"]["snippet"] for item in result["results"]]
    assert len(snippets) > 1
    assert sum(len(snippet) for snippet in snippets) <= 120
    assert result["budget"]["truncated"] is True


def test_mcp_get_section_budget_applies_across_all_returned_chunks(postgres_url: str) -> None:
    run_migrations(postgres_url)
    ids = _seed_multi_chunk_section_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "get_section",
        {"version": "pt862", "section_id": ids["section_id"], "max_chars": 120},
    )

    snippets = [chunk["snippet"] for chunk in result["chunks"]]
    assert len(snippets) == 3
    assert sum(len(snippet) for snippet in snippets) <= 120
    assert result["budget"]["truncated"] is True


def test_mcp_search_docs_exact_mode_prefers_title_and_heading_matches(
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
            "query": "Application Engine Program Elements",
            "search_mode": "exact",
            "limit": 3,
        },
    )

    assert result["match_mode"] == "exact"
    assert result["results"][0]["page"]["page_id"] == ids["program_elements_page_id"]
    assert result["results"][0]["section"]["heading"] == "Application Engine Program Elements"


def test_mcp_search_docs_exact_mode_treats_peoplecode_wildcards_literally(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    ids = _seed_peoplecode_wildcard_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "%This",
            "search_mode": "exact",
            "limit": 5,
        },
    )

    assert {item["page"]["page_id"] for item in result["results"]} == {
        ids["percent_this_page_id"]
    }


def test_mcp_search_docs_exact_mode_returns_diverse_page_candidates(
    postgres_url: str,
) -> None:
    run_migrations(postgres_url)
    ids = _seed_exact_diversity_docs(postgres_url)
    server = create_server(database_url=postgres_url)

    result = _call_tool(
        server,
        "search_docs",
        {
            "version": "pt862",
            "query": "DoStuff",
            "search_mode": "exact",
            "limit": 2,
        },
    )

    assert [item["page"]["page_id"] for item in result["results"]] == [
        ids["do_stuff_page_id"],
        ids["do_stuff_example_page_id"],
    ]


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


def test_mcp_tool_metadata_has_specific_output_schemas_and_workflow_descriptions() -> None:
    server = create_server(database_url="postgresql://example/unused")

    tools = {tool.name: tool for tool in _run(server.list_tools())}

    search_schema = tools["search_docs"].outputSchema
    section_schema = tools["get_section"].outputSchema
    assert search_schema["properties"]["results"]["type"] == "array"
    budget_schema = _schema_property(section_schema, "budget")
    assert set(budget_schema["properties"]) == {"truncated"}
    assert search_schema.get("additionalProperties") is not True
    assert tools["get_page"].outputSchema.get("additionalProperties") is not True
    assert tools["get_page_outline"].outputSchema.get("additionalProperties") is not True
    assert "Use first for questions" in tools["search_docs"].description
    assert "Use after search_docs or get_page_outline" in tools["get_section"].description


def _run[T](awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def _call_tool(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = _run(server.call_tool(name, arguments))
    if isinstance(result, tuple):
        _content, structured_content = result
        return structured_content
    return result.structuredContent


def _read_json_resource(server: Any, uri: str) -> dict[str, Any]:
    contents = _run(server.read_resource(uri))
    return json.loads(contents[0].content)


def _json_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_json_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_json_keys(item))
    return keys


def _schema_property(schema: dict[str, Any], name: str) -> dict[str, Any]:
    prop = schema["properties"][name]
    variants = prop.get("anyOf")
    if variants is not None:
        prop = next(variant for variant in variants if variant.get("type") != "null")
    ref = prop.get("$ref")
    if ref is None:
        return prop
    _, definition_name = ref.rsplit("/", 1)
    return schema["$defs"][definition_name]


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


def _seed_long_section_docs(database_url: str) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
        )
        raw_html = (
            "<html><body><h1>Application Class Methods</h1>"
            "<p>Application classes can expose methods and properties for PeopleCode callers.</p>"
            "<p>Use PeopleBooks to confirm argument order, return values, and restrictions.</p>"
            "</body></html>"
        )
        page, _event = repository.record_fetch_success(
            page_id=repository.queue_page(
                doc_version_id=version.id,
                book_id=book.id,
                normalized_url=(
                    "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/"
                    "applicationclassmethods.html"
                ),
                normalized_path=(
                    "/cd/G41075_01/pt862pbr3/eng/pt/tpcr/applicationclassmethods.html"
                ),
                source_url=(
                    "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/"
                    "applicationclassmethods.html"
                ),
                title="Application Class Methods",
            ).id,
            raw_html=raw_html,
            content_hash="sha256:test",
            status_code=200,
            elapsed_ms=10,
            source_url=(
                "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/"
                "applicationclassmethods.html"
            ),
        )
        content = (
            "Application classes can expose methods and properties for PeopleCode callers. "
            "Use PeopleBooks to confirm argument order, return values, and restrictions. "
            "This longer paragraph verifies that MCP callers receive compact snippets by default."
        )
        repository.replace_page_sections(
            page_id=page.id,
            parser_version="parser-v1",
            sections=[
                SectionInput(
                    stable_id="application-class-methods",
                    heading="Application Class Methods",
                    level=1,
                    section_path=("Application Class Methods",),
                    ordinal=0,
                    content=content,
                    chunks=[
                        ChunkInput(
                            stable_id="application-class-methods-0",
                            ordinal=0,
                            content=content,
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        section = repository.list_sections_for_page(page_id=page.id)[0]
        index_pages(repository=repository, version_code="pt862")

    return {"page_id": page.id, "section_id": section.id}


def _seed_many_search_result_docs(database_url: str) -> None:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
        )
        for index in range(5):
            content = (
                f"BudgetTerm page {index} has enough repeated documentation text to exceed "
                "small aggregate response budgets for MCP clients."
            )
            _queue_page_with_sections(
                repository=repository,
                doc_version_id=version.id,
                book_id=book.id,
                slug=f"BudgetTerm{index}",
                title=f"Budget Term {index}",
                sections=[
                    SectionInput(
                        stable_id=f"budget-term-{index}",
                        heading=f"Budget Term {index}",
                        level=1,
                        section_path=(f"Budget Term {index}",),
                        ordinal=0,
                        content=content,
                        chunks=[
                            ChunkInput(
                                stable_id=f"budget-term-{index}-0",
                                ordinal=0,
                                content=content,
                                metadata={},
                            )
                        ],
                        source_metadata={},
                    )
                ],
            )
        index_pages(repository=repository, version_code="pt862")


def _seed_multi_chunk_section_docs(database_url: str) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
        )
        page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="MultiChunkBudget",
            title="Multi Chunk Budget",
            sections=[
                SectionInput(
                    stable_id="multi-chunk-budget",
                    heading="Multi Chunk Budget",
                    level=1,
                    section_path=("Multi Chunk Budget",),
                    ordinal=0,
                    content="Combined section content is intentionally long.",
                    chunks=[
                        ChunkInput(
                            stable_id=f"multi-chunk-budget-{index}",
                            ordinal=index,
                            content=(
                                f"Chunk {index} contains enough documentation text to exceed "
                                "small aggregate response budgets for MCP clients."
                            ),
                            metadata={},
                        )
                        for index in range(3)
                    ],
                    source_metadata={},
                )
            ],
        )
        section = repository.list_sections_for_page(page_id=page.id)[0]
        index_pages(repository=repository, version_code="pt862")
    return {"section_id": section.id}


def _seed_peoplecode_wildcard_docs(database_url: str) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
        )
        percent_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="PercentThis",
            title="%This",
            sections=[
                SectionInput(
                    stable_id="percent-this",
                    heading="%This",
                    level=1,
                    section_path=("%This",),
                    ordinal=0,
                    content="%This refers to the current object instance.",
                    chunks=[
                        ChunkInput(
                            stable_id="percent-this-0",
                            ordinal=0,
                            content="%This refers to the current object instance.",
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="PlainThis",
            title="Plain This",
            sections=[
                SectionInput(
                    stable_id="plain-this",
                    heading="Plain This",
                    level=1,
                    section_path=("Plain This",),
                    ordinal=0,
                    content="This page should not match a literal percent-prefixed query.",
                    chunks=[
                        ChunkInput(
                            stable_id="plain-this-0",
                            ordinal=0,
                            content="This page should not match a literal percent-prefixed query.",
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        index_pages(repository=repository, version_code="pt862")
    return {"percent_this_page_id": percent_page.id}


def _seed_exact_diversity_docs(database_url: str) -> dict[str, int]:
    with PeopleBooksRepository.connect(database_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=version.seed_url,
        )
        do_stuff_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="DoStuff",
            title="DoStuff",
            sections=[
                SectionInput(
                    stable_id=f"do-stuff-{index}",
                    heading=f"DoStuff Detail {index}",
                    level=1,
                    section_path=(f"DoStuff Detail {index}",),
                    ordinal=index,
                    content=f"DoStuff repeated detail {index}.",
                    chunks=[
                        ChunkInput(
                            stable_id=f"do-stuff-{index}-0",
                            ordinal=0,
                            content=f"DoStuff repeated detail {index}.",
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
                for index in range(3)
            ],
        )
        example_page = _queue_page_with_sections(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            slug="DoStuffExamples",
            title="DoStuff Examples",
            sections=[
                SectionInput(
                    stable_id="do-stuff-examples",
                    heading="DoStuff Examples",
                    level=1,
                    section_path=("DoStuff Examples",),
                    ordinal=0,
                    content="DoStuff examples show valid usage.",
                    chunks=[
                        ChunkInput(
                            stable_id="do-stuff-examples-0",
                            ordinal=0,
                            content="DoStuff examples show valid usage.",
                            metadata={},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        index_pages(repository=repository, version_code="pt862")
    return {
        "do_stuff_page_id": do_stuff_page.id,
        "do_stuff_example_page_id": example_page.id,
    }


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
