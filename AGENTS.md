# AGENTS.md

## Maintenance

- Keep this file current after code, schema, dependency, CLI, MCP, or architecture changes.
- Remove stale guidance in the same change that makes it stale.
- Keep bullets short, factual, and non-duplicated.
- Treat the project as finished; prefer documenting current behavior over planned work.

## Project

- Scrapes Oracle PeopleBooks into PostgreSQL and exposes the content through MCP.
- Seed source: Oracle PeopleSoft PeopleTools 8.62.
- Seed URL: `https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home`.
- Initial book: PeopleCode API Reference (`tpcr`).
- New PeopleBooks versions are config/data additions, not rewrites.

## Stack

- Python 3.14 managed with `uv`; metadata and tool defaults live in `pyproject.toml`.
- Package: `src/peoplebooks_mcp`.
- PostgreSQL with Alembic migrations in `migrations/versions`.
- HTTP/parsing: `httpx`, BeautifulSoup, `lxml`; Playwright stays optional for non-static HTML.
- CLI/server: Typer and the MCP Python SDK.
- Retrieval uses PostgreSQL full-text search before embeddings.

## Scraper

- Default config lives in `peoplebooks_mcp.config`; local overrides use `peoplebooks.toml` or `PEOPLEBOOKS_*` env vars.
- Use conservative HTTP settings: low concurrency, delay, timeout, retries, backoff, and the project user agent.
- Do not enforce `robots.txt`.
- Fetching uses `peoplebooks_mcp.scraper.fetcher.PeopleBooksFetcher`.
- Discovery parses the Oracle home `Products` tree, stores normalized Oracle URLs, and persists book-scoped category/book/page chains in `nav_nodes`.
- `peoplebooks discover --book tpcr` supports the configured seed fallback when the home page has no `Products` tree.
- Full-tree discovery keeps `tpcr` as the PeopleCode API Reference book and preserves existing page identities.
- `scrape --limit N` processes the next eligible pages and resumes after interruption.
- Reparse from stored raw HTML without refetching Oracle.

## Data

- Core tables: `doc_versions`, `books`, `nav_nodes`, `pages`, `sections`, `chunks`, `fetch_events`.
- Page uniqueness includes `doc_version_id` plus normalized path or URL.
- Store raw HTML, normalized URL, source metadata, content hash, parser version, fetch status, timestamps, and append-only fetch diagnostics.
- Parse leaf pages into H1/H2/H3 sections and retrieval chunks.
- Store chunk full-text vectors in `chunks.search_vector` with a GIN index.
- `peoplebooks_mcp.indexing.index_pages` refreshes chunk vectors and marks pages indexed.
- Repository entry point: `peoplebooks_mcp.repositories.PeopleBooksRepository`.
- Repository search returns version, book, page, section path, source URL, snippets, rank, and stable section/chunk IDs.

## CLI

- `peoplebooks discover --version pt862 --book tpcr`
- `peoplebooks discover --version pt862 --all-books`
- `peoplebooks scrape --version pt862 --limit 25`
- `peoplebooks status --version pt862`
- `peoplebooks reparse --version pt862 --parser-version X`
- `peoplebooks index --version pt862`
- `peoplebooks serve-mcp`
- `discover` and `scrape` print updating progress counters; `status` prints discovered, queued, fetched, failed, parsed, and indexed counts.
- `serve-mcp` starts the read-only MCP server over stdio.

## MCP

- MCP is read-only; handlers never scrape live Oracle pages.
- Tools: `health`, `search_docs`, `find_pages`, `get_page_outline`, `get_page`, `get_section`, `list_books`.
- Resources expose versions, version books, book pages, pages, and sections.
- Results are retrieval-oriented, compact by default, and omit raw HTML plus crawler/debug fields.
- Useful results include version, book, page, section path, source URL, snippet, rank, and stable IDs.
- Prefer `search_docs` or `find_pages`, then returned `page_id`/`section_id`, instead of guessing page paths.
- Use `search_docs(search_mode="exact")` for specific API, page, or heading lookups.
- `search_docs` uses strict PostgreSQL full-text search first, then a bounded relaxed fallback when strict search returns no hits.
- Use `get_page_outline` for paged headings before requesting body text with `get_section`.
- `search_docs` and `get_section` support `max_chars`; `get_section(detail="full")` is for exact section text.
- `health` reports schema revision, required search columns, and parsed/indexed content readiness.

## Testing

- Use fixture parser tests for home, book, and leaf HTML.
- Cover fetch retry, backoff, timeout, content hashing, and failure recording.
- Test repository, CLI queue/resume/limit/status, search, and MCP responses over known indexed content.
- PostgreSQL tests require `PEOPLEBOOKS_TEST_DATABASE_URL` in the environment or `.env`, pointing to a disposable database whose name contains `test`.
