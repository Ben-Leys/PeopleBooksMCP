# AGENTS.md

## Maintenance

- Keep this file current after code, schema, dependency, CLI, MCP, or architecture changes.
- Remove stale instructions in the same change that makes them stale.
- Keep bullets short, factual, and non-duplicated.
- Prefer actual project state over planned future work.

## Project

- Goal: scrape Oracle PeopleBooks into PostgreSQL and expose it through MCP.
- Seed source: Oracle PeopleSoft PeopleTools 8.62.
- Seed URL: `https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home`.
- First book: PeopleCode API Reference (`tpcr`).
- New PeopleBooks versions should be config/data additions, not rewrites.

## Stack

- Python 3.14.
- `uv` for project and dependency management.
- Project metadata and tool defaults live in `pyproject.toml`.
- Python package: `src/peoplebooks_mcp`.
- Local PostgreSQL from day one.
- Alembic migrations live in `migrations/versions`.
- `httpx` for HTTP-first fetching.
- BeautifulSoup plus `lxml` for parsing.
- Typer for the CLI.
- PostgreSQL full-text search before embeddings.
- MCP Python SDK for the server.
- Keep Playwright optional unless static HTML fails.

## Scraper

- Default seed config lives in `peoplebooks_mcp.config`; local overrides use `peoplebooks.toml` or `PEOPLEBOOKS_*` env vars.
- Use conservative requests: low concurrency, delay, timeout, retries, backoff, and project user agent.
- Do not enforce `robots.txt`.
- Store raw HTML, normalized URL, source metadata, content hash, parser version, fetch status, and timestamps.
- Keep discovered pages and scrape state in PostgreSQL.
- Discovery parses home/book navigation, queues book page links, and stores normalized Oracle URLs.
- Fetching uses `peoplebooks_mcp.scraper.fetcher.PeopleBooksFetcher`.
- `scrape --limit N` processes the next eligible pages and resumes after interruption.
- Support reparse from stored raw HTML without refetching Oracle.

## Data

- Core tables: `doc_versions`, `books`, `nav_nodes`, `pages`, `sections`, `chunks`, `fetch_events`.
- Page uniqueness includes `doc_version_id` and normalized path or URL.
- Parse leaf pages into H1/H2/H3 sections and retrieval chunks.
- Full-text vectors on chunks are planned for Phase 5; Phase 2 stores chunk text and metadata.
- Keep fetch diagnostics append-only.
- PostgreSQL repository entry point: `peoplebooks_mcp.repositories.PeopleBooksRepository`.

## CLI

- `peoplebooks discover --version pt862 --book tpcr` fetches seed navigation and queues pages.
- `peoplebooks scrape --version pt862 --limit 25`.
- `peoplebooks status --version pt862` prints discovered, queued, fetched, failed, parsed, and indexed counts.
- `peoplebooks reparse --version pt862 --parser-version X`.
- `peoplebooks index --version pt862`.
- `peoplebooks serve-mcp`.
- `scrape`, `reparse`, `index`, and `serve-mcp` remain Typer stubs until their implementation phases.

## MCP

- MCP server behavior is planned for Phase 6; current module is a stub.
- MCP must be read-only until explicitly changed.
- MCP handlers must never scrape live Oracle pages.
- Planned tools: `search_docs`, `get_page`, `get_section`, `list_books`.
- Planned resources: versions, books, pages, sections.
- Planned results include version, book, page, section path, source URL, snippet, and stable IDs.

## Testing

- Use fixture parser tests for home, book, and leaf HTML.
- Test fetch retry, backoff, timeout, hash, and failure recording.
- Test repositories against local PostgreSQL.
- PostgreSQL tests require `PEOPLEBOOKS_TEST_DATABASE_URL` pointing to a disposable database whose name contains `test`.
- Test CLI queue, resume, `--limit`, and status behavior.
- Test search and MCP responses over known indexed content.
