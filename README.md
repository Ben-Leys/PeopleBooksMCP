# PeopleBooks MCP

PeopleBooks MCP scrapes Oracle PeopleBooks into PostgreSQL and serves the parsed
documentation through a read-only MCP server for AI agents.

The configured seed is PeopleTools 8.62, with `tpcr` for the PeopleCode API Reference.
Full-tree discovery finds the other books exposed by Oracle for that version. Adding a
different documentation-version seed currently requires an entry in
`src/peoplebooks_mcp/config.py`.

## Stack

- Python 3.14
- `uv` for dependency and command management
- PostgreSQL for scrape state, parsed content, and full-text search
- Alembic migrations
- `httpx`, BeautifulSoup, and `lxml` for fetching and parsing
- Typer CLI
- MCP Python SDK over stdio

## Configuration

Runtime defaults live in `src/peoplebooks_mcp/config.py`.

Local overrides can be supplied with:

- `peoplebooks.toml`
- `PEOPLEBOOKS_CONFIG`
- `PEOPLEBOOKS_DATABASE_URL`
- `PEOPLEBOOKS_USER_AGENT`
- `PEOPLEBOOKS_REQUEST_TIMEOUT_SECONDS`
- `PEOPLEBOOKS_SEARCH_TIMEOUT_SECONDS`
- `PEOPLEBOOKS_TOOL_RESULT_MODE`

Environment variables must be set in the process environment. Runtime commands do not
load `.env` automatically; use `peoplebooks.toml`, `PEOPLEBOOKS_CONFIG`, or export the
variables before starting the command. PostgreSQL tests are the exception and can read
`PEOPLEBOOKS_TEST_DATABASE_URL` from `.env`.

Example:

```toml
[settings]
database_url = "postgresql://peoplebooks:peoplebooks@localhost:5432/peoplebooks"
user_agent = "PeopleBooksMCP/0.1.0"
request_timeout_seconds = 20
search_timeout_seconds = 10
tool_result_mode = "structured"
```

## Database

Create a local PostgreSQL database, then run migrations:

```powershell
uv run alembic upgrade head
```

Tests that use PostgreSQL require `PEOPLEBOOKS_TEST_DATABASE_URL` to point at a
disposable database whose name contains `test`.

## Ingestion Flow

Discover and queue the configured PeopleCode API Reference book:

```powershell
uv run peoplebooks discover --version pt862 --book tpcr
```

Discover all books in the Oracle Products tree:

```powershell
uv run peoplebooks discover --version pt862 --all-books
```

Fetch and parse queued pages in resumable batches:

```powershell
uv run peoplebooks scrape --version pt862 --limit 25
```

Show progress:

```powershell
uv run peoplebooks status --version pt862
```

The total discovered page count is printed separately from an explicitly labelled block of
mutually exclusive current lifecycle states, including `fetched, awaiting parse` and
`parsed, awaiting index`.

Rebuild Markdown sections and semantic chunks from stored raw HTML without
refetching Oracle. Stable sections and chunks retain their database IDs. Successful scrape and
reparse operations index each page immediately:

```powershell
uv run peoplebooks reparse --version pt862 --parser-version v2
```

Bulk-refresh PostgreSQL full-text vectors when repairing or rebuilding an existing index:

```powershell
uv run peoplebooks index --version pt862
```

## Raw HTML Policy

Raw HTML is stored so parser changes can be applied later without fetching Oracle
again. It is not exposed through MCP because it is large, noisy, and inefficient
for agent context. MCP tools and resources return parsed, compact documentation
payloads only.

## MCP Server

Start the read-only MCP server over stdio:

```powershell
uv run peoplebooks serve-mcp
```

Example MCP client command configuration:

```json
{
  "mcpServers": {
    "peoplebooks": {
      "command": "uv",
      "args": ["run", "peoplebooks", "serve-mcp"],
      "cwd": "C:\\Users\\BLeys\\PycharmProjects\\PeopleBooksMCP"
    }
  }
}
```

## Agent Workflow

Use the smallest useful result first:

1. `search_docs` answers questions with compact plain-text snippets and
   `page_id`/`section_id` handles.
2. Answer directly from those snippets when they contain enough context.
3. `get_section` retrieves more Markdown only when a returned snippet is insufficient; pass its
   returned `section_id` unchanged.
4. `find_pages` locates likely pages from indexed book/page titles, paths, and headings without
   scanning or returning body content.
5. `get_page_outline` returns paged headings for one page.
6. `health` diagnoses database/index readiness, and `list_books` supplies book codes only when a
   search genuinely needs scoping.

`get_section` returns one Markdown `content` page. If `next_cursor` is present,
   pass it back with the same section handle to retrieve the lossless continuation.

Successful tool calls default to `tool_result_mode = "structured"`: data is returned in
`structuredContent`, and the legacy text content block stays empty to avoid duplicating
the JSON payload. Set the mode to `"compatible"` for older MCP clients that require the
same payload serialized into a text content block. Tool failures set `isError = true` and
always include a concise text recovery message as well as structured error details.
`search_docs` and `find_pages` share the configured search statement timeout and return the
specific `search_timeout` error when it expires.

For code-writing agents, start with `search_docs` using a focused PeopleCode term,
method, class, property, or error phrase. Use `search_mode="exact"` when checking a
specific API/page/heading name.

Tool input schemas describe every parameter. `search_docs.max_chars` budgets the complete
serialized response, while `get_section.max_chars` budgets Markdown content only. Continuation
cursors are opaque and must be passed back unchanged with the same section identifier.

## Development

Run the test suite:

```powershell
uv run pytest -q
```

Run linting:

```powershell
uv run ruff check .
```
