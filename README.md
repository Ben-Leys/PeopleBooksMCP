# PeopleBooks MCP

PeopleBooks MCP scrapes Oracle PeopleBooks into PostgreSQL and serves the parsed
documentation through a read-only MCP server for AI agents.

The initial seed is PeopleTools 8.62, with `tpcr` for the PeopleCode API Reference.
The project is designed so new PeopleBooks versions and books can be added through
configuration/data rather than rewrites.

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

Example:

```toml
[settings]
database_url = "postgresql://peoplebooks:peoplebooks@localhost:5432/peoplebooks"
user_agent = "PeopleBooksMCP/0.1.0"
request_timeout_seconds = 20
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

Rebuild parsed sections and chunks from stored raw HTML without refetching Oracle:

```powershell
uv run peoplebooks reparse --version pt862 --parser-version v2
```

Refresh PostgreSQL full-text vectors:

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

1. `health` checks database, schema, parse, and index readiness.
2. `list_books` finds book codes for scoping searches.
3. `search_docs` answers most questions with compact plain-text snippets and
   `page_id`/`section_id` handles.
4. `find_pages` locates likely pages without returning content.
5. `get_page_outline` returns paged headings for one page.
6. `get_section` returns compact section snippets by default; request
   `detail="full"` only when exact content is needed.

Tool calls return data in `structuredContent`; the legacy text content block is
left empty to avoid duplicating the JSON payload.

For code-writing agents, start with `search_docs` using a focused PeopleCode term,
method, class, property, or error phrase. Use `search_mode="exact"` when checking a
specific API/page/heading name.

## Development

Run the test suite:

```powershell
uv run pytest -q
```

Run linting:

```powershell
uv run ruff check .
```
