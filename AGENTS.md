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
- Discovery parses the Oracle home `Products` tree, queues book page links, and stores normalized Oracle URLs.
- Full-tree discovery persists `Products` and category ancestors as book-scoped `nav_nodes` above each book root.
- `peoplebooks discover --book tpcr` still supports the configured seed fallback when a home page has no Products tree.
- Full-tree discovery keeps `tpcr` as the discovered PeopleCode API Reference book and preserves existing page identities.
- Fetching uses `peoplebooks_mcp.scraper.fetcher.PeopleBooksFetcher`.
- `scrape --limit N` processes the next eligible pages and resumes after interruption.
- Support reparse from stored raw HTML without refetching Oracle.

## Data

- Core tables: `doc_versions`, `books`, `nav_nodes`, `pages`, `sections`, `chunks`, `fetch_events`.
- Page uniqueness includes `doc_version_id` and normalized path or URL.
- `nav_nodes` store book-scoped Oracle category/book/page parent chains from the `Products` tree.
- Parse leaf pages into H1/H2/H3 sections and retrieval chunks.
- Full-text vectors on chunks are stored in `chunks.search_vector` and indexed with GIN.
- `peoplebooks_mcp.indexing.index_pages` refreshes chunk vectors and marks indexed pages.
- Repository search returns version, book, page, section path, source URL, snippets, rank, and stable section/chunk IDs.
- Keep fetch diagnostics append-only.
- PostgreSQL repository entry point: `peoplebooks_mcp.repositories.PeopleBooksRepository`.

## CLI

- `peoplebooks discover --version pt862 --book tpcr` fetches seed navigation and queues pages.
- `peoplebooks discover --version pt862 --all-books` discovers every book found in the Oracle `Products` tree.
- `discover` prints an updating book/navigation/page counter while it runs.
- `peoplebooks scrape --version pt862 --limit 25`.
- `scrape` prints an updating processed/scraped/failed/parsed page counter while it runs.
- `peoplebooks status --version pt862` prints discovered, queued, fetched, failed, parsed, and indexed counts.
- `peoplebooks reparse --version pt862 --parser-version X`.
- `peoplebooks index --version pt862` refreshes PostgreSQL full-text vectors for parsed chunks.
- `peoplebooks serve-mcp`.
- `serve-mcp` remains a Typer stub until its implementation phase.

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
- PostgreSQL tests require `PEOPLEBOOKS_TEST_DATABASE_URL` in the environment or `.env`, pointing to a disposable database whose name contains `test`.
- Test CLI queue, resume, `--limit`, and status behavior.
- Test search and MCP responses over known indexed content.
