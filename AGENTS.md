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
- Initial configured book seed: PeopleCode API Reference (`tpcr`).
- Full-tree discovery adds books from Oracle data; new documentation-version seeds currently require
  an entry in `peoplebooks_mcp.config`.

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
- Reparse from stored raw HTML without refetching Oracle; unchanged stable sections/chunks retain database IDs.

## Data

- Core tables: `doc_versions`, `books`, `nav_nodes`, `pages`, `sections`, `chunks`, `fetch_events`.
- Page uniqueness includes `doc_version_id` plus normalized path or URL.
- Store raw HTML, normalized URL, source metadata, content hash, parser version, fetch status, timestamps, and append-only fetch diagnostics.
- Parse leaf pages into H1/H2/H3 Markdown sections and roughly 1,200-2,000-character semantic chunks.
- Preserve code blocks, lists, tables, warnings, and links; heading-only sections receive searchable chunks.
- Successful parsing refreshes that page's vectors and marks it indexed in the same transaction.
- Store English and simple chunk vectors with GIN indexes; trigram identifier metadata covers book/page titles, paths, and headings.
- `peoplebooks_mcp.indexing.index_pages` remains available for bulk vector refreshes.
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
- `discover` and `scrape` print updating progress counters; `status` labels its total separately from
  mutually exclusive current lifecycle states.
- `serve-mcp` starts the read-only MCP server over stdio.

## MCP

- MCP is read-only; handlers never scrape live Oracle pages.
- Tools: `health`, `search_docs`, `find_pages`, `get_page_outline`, `get_section`, `list_books`.
- Resources expose versions, version books, paged book pages, pages, and sections.
- Successful tool results default to structured-only output; compatible mode duplicates JSON as text.
- Configure tool output with `tool_result_mode` or `PEOPLEBOOKS_TOOL_RESULT_MODE`.
- Tool failures set `isError`, include concise recovery text, and hide internal exceptions.
- Results are retrieval-oriented, compact by default, and omit raw HTML plus crawler/debug fields.
- Search snippets are plain text without highlight markup.
- Search defaults to five results with at most one result per page.
- The version value `latest` aliases the default `pt862` documentation version.
- For questions, call `search_docs` directly; do not preflight with `health`, `list_books`, or `find_pages`.
- `find_pages` is navigation-only and returns no answer text.
- Search results are flat and include `book_code`, `page_id`, title, `section_id`, relative path, source URL, and snippet.
- Prefer `search_docs` or `find_pages`, then returned `page_id`/`section_id`, instead of guessing page paths.
- Use `search_docs(search_mode="exact")` for specific API, page, or heading lookups.
- `search_docs` keeps strong strict English FTS results and falls back below a minimum strict score to bounded English/simple FTS plus identifier reranking.
- `find_pages` ranks indexed book/page title, path, and heading metadata without scanning chunk bodies.
- `search_docs` and `find_pages` share a configurable 10-second default statement timeout and return `search_timeout` when it expires.
- Use `get_page_outline` for paged headings before requesting body text with `get_section`.
- `search_docs.max_chars` budgets its complete serialized response; `get_section.max_chars` budgets content.
- `get_section` returns one Markdown `content` field and an opaque `next_cursor` for lossless continuation.
- MCP input schemas describe parameter use, response budgets, and opaque cursor reuse.
- Book-page resources return at most 100 pages plus a `next_uri` continuation.
- `health` reports schema revision, required search columns, and parsed/indexed content readiness.

## Testing

- Use fixture parser tests for home, book, and leaf HTML.
- Cover fetch retry, backoff, timeout, content hashing, and failure recording.
- Test repository, CLI queue/resume/limit/status, search, and MCP responses over known indexed content.
- PostgreSQL tests require `PEOPLEBOOKS_TEST_DATABASE_URL` in the environment or `.env`, pointing to a disposable database whose name contains `test`.
