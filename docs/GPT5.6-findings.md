• ## Verdict

The project has a strong foundation, but two issues currently prevent it from being genuinely agent-grade at scale:

1. Documentation is not meaningfully chunked, so long sections and formatted code cannot be retrieved correctly.
2. Relaxed search is too slow for the natural-language questions agents will send.

I would fix those before spending more time removing individual JSON fields.

The current uncommitted MCP reductions are directionally good: removing repeated query/filter/version data, ranks, chunk
internals, markup, and duplicated automatic text is sensible. I preserved all existing changes and made no
edits.

## What is already professional

- Clear separation between ingestion and read-only MCP serving.
- Raw HTML is retained for reparsing but never exposed to agents.
- PostgreSQL constraints, composite foreign keys, migrations, atomic fetch events, and parameterized SQL are solid.
- Search results provide source URLs and page/section handles for drill-down.
- Compact defaults, response budgets, strict Pydantic output models, and read-only MCP annotations are thoughtful.
- The real database is healthy: 4,762 indexed pages and 36,718 indexed chunks.
- All 87 tests pass; linting and compilation pass. Instrumented coverage is approximately 91%.

## Highest-priority improvements

### 1. Implement real semantic chunking and lossless retrieval

Every non-empty section currently becomes exactly one chunk in /C:
/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/parser/leaf.py:129. In the live corpus:

- 36,718 non-empty sections each have one chunk.
- The largest section is 317,112 characters.
- 7,080 heading-only sections have no searchable chunk.

get_section(detail="full") then budgets both the section and its identical chunk /C:
/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/mcp_server.py:827, duplicating content. Its truncator
also collapses all
whitespace /C:/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/mcp_server.py:1039.

In a real 4,914-character example, “full” returned:

- The same first 4,000 characters twice.
- None of the original 44 line breaks.
- No way to retrieve the remainder.

That directly contradicts the documented “exact section text” behavior.

Recommended design:

- Convert HTML into compact Markdown preserving code blocks, lists, tables, warnings, and links.
- Chunk on semantic block boundaries at roughly 1,200–2,000 characters.
- Keep code/table blocks intact where possible.
- Give every heading a searchable record, even with no body.
- Make get_section return one content field, not section content plus chunks.
- Add an opaque continuation cursor so every section can be retrieved.
- Preserve section/chunk database IDs through reparsing, or expose a genuinely stable handle.

### 2. Replace the relaxed substring scan

The relaxed fallback cross-joins every query term with every chunk and repeatedly evaluates %LIKE% over content /C:
/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/repositories/postgres.py:1412.

Live timings for ordinary agent questions were:

- 16.3 seconds
- 21.5 seconds

Strict GIN-backed searches generally took 0.1–0.2 seconds.

Use a GIN-supported OR-style full-text fallback, calculate term coverage over a bounded candidate set, and then rerank.
For PeopleCode identifiers, combine:

- English FTS for prose.
- simple FTS or a normalized identifier column.
- Trigram matching for %This, SQLExec, camel-case APIs, filenames, and headings.
- Page diversification so five results are not all sections from one page.
- A database statement_timeout.

Embeddings are not the next priority. API documentation benefits more from good lexical, identifier, and phrase
retrieval.

### 3. Reduce results structurally, not only field-by-field

The default search returns up to ten results but shares only 450 snippet characters across them. A live CreateArray
lookup produced:

- 5,266 serialized characters.
- 450 snippet characters.
- Approximately 4,816 characters of metadata and JSON structure.
- An average snippet of only 45 characters.

The generated seven-tool catalog is about 19,126 characters of schemas and descriptions. get_page and get_page_outline
are behaviorally identical /C:/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/mcp_server.py:316,
duplicating more than 7,000 schema characters between them.

I recommend:

- Default to three results, with one high-quality hit per page.
- Remove get_page; retain get_page_outline.
- Flatten search results and remove the now-pointless chunk: {snippet} wrapper.
- Omit echoed version/input values on successful calls.
- Return a relative section path without repeating the page title.
- Measure the complete serialized response, not just body text.
- Remove or paginate the book-pages resource. The current tpcr pages resource is 297,719 characters for 1,141 pages /C:
  /Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/mcp_server.py:551.

A better default result shape would be:

{
"match": "strict",
"truncated": false,
"results": [{
"page_id": 1826,
"section_id": 23680,
"book_code": "tpcl",
"title": "PeopleCode Built-in Functions and Language Constructs: C",
"path": ["CreateArray", "Syntax"],
"snippet": "CreateArray(paramlist) ...",
"source_url": "https://docs.oracle.com/..."
}]
}

### 4. Structured-only output compatibility policy — implemented

Successful tools default to structured-only results to avoid duplicating JSON. Operators can set
`tool_result_mode = "compatible"` or `PEOPLEBOOKS_TOOL_RESULT_MODE=compatible` for clients that require the structured
payload serialized into legacy text content. Recoverable tool failures set `isError=true`, include concise recovery
text and structured error details, and log internal database exceptions without exposing them to clients.

### 5. Fix the ingestion lifecycle

Failed pages are terminal: queue selection only includes queued and fetched-but-unparsed pages /C:
/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/repositories/postgres.py:607. The schema defines
fetching, but it is
never used, and pages are not atomically claimed. Two scraper processes could therefore fetch the same pages.

Implement:

- Atomic claiming with FOR UPDATE SKIP LOCKED.
- A claim timestamp/lease for interrupted workers.
- Retry scheduling and a retry-failed or requeue command.
- Persistent HTTP client reuse instead of opening a client/TLS connection for every page.
- Incremental indexing after parsing so search is never silently stale.

The status output is also misleading. The fully indexed live corpus reports fetched: 0 and parsed: 0 because those are
treated as mutually exclusive current states /C:/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/
repositories/postgres.py:870. Use cumulative timestamp-based counts or label them explicitly as current states.

## Agent perspective

A typical agent will:

1. Read tool names, descriptions, and input schemas—not the repository README.
2. Send the user’s full question to search_docs.
3. Follow a returned section_id into get_section.
4. Request an outline only when search is ambiguous.

You support that flow partially. The source URL, handles, match mode, compact snippets, and truncation indicator are
exactly the right ingredients.

What is missing is equally important:

- Natural questions can trigger 20-second searches.
- Ten default results leave too little useful text per result.
- search_mode and max_chars have no concise parameter descriptions in the exposed schema.
- get_page versus get_page_outline is ambiguous.
- Long sections have no continuation.
- Code and tables lose formatting.
- detail="normal" behaves the same as compact.
- Numeric section IDs change after reparsing because sections are deleted and reinserted /C:
  /Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/repositories/postgres.py:1049.

The ideal agent contract is: search once, get three useful candidates, fetch one formatted section, and continue only if
explicitly indicated.

## Remaining professional polish

- The “new versions are configuration additions” claim is not implemented: versions and books are hard-coded, while TOML
  only reads [settings] /C:/Users/BLeys/PycharmProjects/PeopleBooksMCP/src/peoplebooks_mcp/config.py:46.
- docs/IMPLEMENTATION_PLAN.md contains stale phase language and contradicts completed full-tree discovery.
- mcp>=1.15 needs a <2 upper bound /C:/Users/BLeys/PycharmProjects/PeopleBooksMCP/pyproject.toml:11. The official stable
  SDK documentation specifically recommends this before v2 lands. Official MCP Python SDK v1 branch
  (https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)

- The server advertises the MCP SDK version rather than the PeopleBooks server version.
- The wheel does not bundle Alembic migrations/configuration, so installation is not self-contained.
- The MCP process should use a dedicated PostgreSQL read-only role plus statement timeouts; annotations alone do not
  enforce read-only access.
- mcp_server.py and repositories/postgres.py should be split into catalog, search, ingestion, payload, tool, and
  resource modules.
- ruff format --check currently reports seven files needing formatting.
- There is no CI, license, security policy, contribution guidance, or end-to-end stdio protocol test.

My recommended implementation order is: semantic chunking and paged Markdown retrieval; indexed relaxed search; MCP
surface simplification and error compatibility; ingestion/configuration robustness; then packaging, CI, and
documentation polish.
