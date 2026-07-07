# AGENTS.md

## Project Purpose

PeopleBooksMCP is intended to scrape Oracle PeopleBooks documentation, store it in a structured PostgreSQL database, and
expose the current PeopleBooks version through an MCP server for AI-assisted reference.

Initial source:

- Oracle PeopleSoft PeopleTools 8.62
- Start URL: `https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home`
- First target book: PeopleCode API Reference (`tpcr`)

PeopleTools 8.62 is the default seed version, not a hardcoded assumption. The code should allow later PeopleBooks
versions to be added through configuration and database rows.

## Baseline Decisions

- Use Python 3.14.
- Use `uv` for dependency and project management.
- Use local PostgreSQL from day one.
- Build a robust scraper/data foundation first, while validating it through one complete PeopleBook.
- Use HTTP-first fetching with `httpx`.
- Use BeautifulSoup plus `lxml` for HTML parsing.
- Keep Playwright out of the core path initially; it may become an optional fallback if a future Oracle page requires
  browser execution.
- Preserve raw HTML in PostgreSQL alongside extracted structure and text.
- Use PostgreSQL full-text search first; do not add embeddings or `pgvector` until the text extraction, chunking, and
  ranking behavior are proven.
- Build a CLI-first workflow. Do not make scraping a long-running service in the first version.
- Expose both MCP tools and MCP resources once indexed content exists.

## Scraping Policy

The scraper should be conservative by default:

- Use sequential or near-sequential requests.
- Apply a configurable delay between requests.
- Use request timeout, retry, and exponential backoff behavior.
- Send a project-identifying user agent.
- Cache/preserve fetched page content by storing raw HTML and content hashes.
- Do not enforce `robots.txt`; this is an explicit project-owner decision.

Scraping must be resumable and incremental. The database should keep a list of discovered pages and their scrape status.
The CLI must support a limit argument, so a command such as `scrape --limit 25` processes the next 25 eligible pages
until the queue is complete.

## Architecture

Keep the system split into focused modules:

- `crawler`: discover PeopleBooks versions, books, navigation nodes, and leaf pages from Oracle's static HTML
  navigation.
- `fetcher`: fetch pages via `httpx`, handling rate limits, retries, timeouts, content hashes, and raw HTML
  preservation.
- `parser`: parse product home pages, subject/book pages, navigation trees, and leaf topic pages using
  BeautifulSoup/lxml.
- `storage`: own PostgreSQL schema access, repository methods, and migrations.
- `ingest`: orchestrate discovery, queueing, fetching, parsing, storing, reprocessing, and indexing.
- `search`: implement PostgreSQL full-text indexing and retrieval over chunks.
- `mcp`: expose indexed content through MCP tools and resources.
- `cli`: expose operational commands through Typer.

Avoid one-shot scripts for core behavior. Prefer idempotent functions and commands that can be safely rerun.

## Data Model

The database should preserve both crawl state and documentation structure.

Core entities:

- `doc_versions`: PeopleBooks source/version rows, including base URL, product line, version label, discovered
  timestamp, and scrape status.
- `books`: book-level entries such as PeopleCode API Reference, including category and subject metadata.
- `nav_nodes`: full Oracle navigation hierarchy, including category, book, chapter/header, and page nodes, with
  parent/child/order fields.
- `pages`: canonical leaf pages with normalized URL/path, title, source metadata, raw HTML, content hash, fetch status,
  timestamps, and parser version.
- `sections`: H1/H2/H3-derived sections within a page, preserving heading level, order, anchor/source IDs, title,
  heading path, and text.
- `chunks`: retrieval-sized text chunks linked to page and section, including order, character/token counts, snippet
  text, and `tsvector`.
- `fetch_events`: append-only log of fetch attempts, HTTP status, elapsed time, errors, and hash changes.

Page uniqueness must include `doc_version_id` and normalized URL/path so multiple PeopleTools versions can coexist.

Do not lose raw HTML when parser logic changes. Reprocessing should be possible without refetching Oracle.

## CLI Shape

Expected initial commands:

- `peoplebooks discover --version pt862 --book tpcr`
    - Discover the configured book navigation.
    - Upsert `books`, `nav_nodes`, and pending `pages`.

- `peoplebooks scrape --version pt862 --limit 25`
    - Fetch and parse the next 25 pending or retryable pages.
    - Store raw HTML, metadata, sections, chunks, content hashes, and fetch events.

- `peoplebooks status --version pt862`
    - Show discovered page counts, pending/succeeded/failed counts, last scrape time, and recent failures.

- `peoplebooks reparse --version pt862 --parser-version X`
    - Rebuild extracted metadata, sections, and chunks from stored raw HTML.

- `peoplebooks index --version pt862`
    - Rebuild PostgreSQL full-text vectors.

- `peoplebooks serve-mcp`
    - Start the MCP server against already indexed database content.

The MCP server must not scrape live. Scraping is an explicit CLI operation.

## Search And MCP

Initial retrieval uses PostgreSQL full-text search over chunks.

Search results should include enough information for precise source attribution:

- version
- book
- page title
- section heading path
- source URL
- snippet text
- stable page/section/chunk IDs

Initial MCP tools:

- `search_docs(query, version?, book?, limit?)`
- `get_page(page_id or url, include_sections?)`
- `get_section(section_id)`
- `list_books(version?)`

Initial MCP resources:

- version list
- book list per version
- page resources by stable IDs
- section resources by stable IDs

Keep the MCP layer read-only until there is an explicit product reason to add write operations.

## Dependencies

Expected initial dependencies:

- Python 3.14
- `uv`
- `httpx`
- `beautifulsoup4`
- `lxml`
- PostgreSQL
- `psycopg` or SQLAlchemy
- Alembic if SQLAlchemy is used
- Typer
- Pydantic or dataclasses for typed config and parsed document models
- MCP Python SDK
- Pytest
- `respx` or `pytest-httpx`
- Ruff
- mypy or pyright

Choose dependency details in sympathy with the existing code once the project is scaffolded. Do not add large
infrastructure before it serves the scraper, storage, CLI, or MCP path.

## Testing Expectations

Start with fixture-driven tests.

Required test areas:

- Parser tests using saved Oracle HTML samples for the home page, book page, and leaf topic page.
- Fetcher tests for retry, timeout, backoff, content hash, and failure recording behavior.
- Repository tests against local PostgreSQL.
- CLI tests for discovery, queue resume behavior, `--limit`, and status reporting.
- Search tests for chunk ranking and source metadata.
- MCP tests for tool/resource responses over known indexed content.

Fetching, parsing, storing, indexing, and MCP serving should be separately testable.

## Development Conventions

- Keep Oracle source URLs, version IDs, parser versions, and content hashes explicit.
- Normalize URLs and paths consistently before storing or comparing them.
- Prefer structured parsers over ad hoc string parsing.
- Treat parser output as versioned. If parser behavior changes, update parser version and support reparse workflows.
- Use idempotent upserts for discovery and ingestion.
- Store enough fetch diagnostics to explain failures without rerunning the scraper.
- Do not mix live scraping into MCP request handlers.
- Keep the first implementation focused on PeopleTools 8.62 and the PeopleCode API Reference, but design boundaries so
  new books and versions are configuration/data additions.

