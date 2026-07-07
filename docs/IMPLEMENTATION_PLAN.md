# PeopleBooks MCP Implementation Plan

**Goal:** Build a working Python 3.14 service that scrapes Oracle PeopleBooks into PostgreSQL and exposes indexed documentation through read-only MCP tools/resources.

## Phase 1: Project Foundation

- Initialize a `uv` Python project with package, CLI entry point, test setup, lint/format defaults, and local settings.
- Add dependencies: `httpx`, `beautifulsoup4`, `lxml`, `typer`, PostgreSQL driver/migrations, pytest tooling, and MCP Python SDK.
- Create a small app layout for config, database access, repositories, scraper, parser, indexing, CLI, and MCP server.
- Add seed configuration for PeopleTools 8.62 and the PeopleCode API Reference book (`pt862` / `tpcr`).
- Tests: import/package smoke tests, config loading tests, and CLI help tests.

## Phase 2: PostgreSQL Data Model

- Add migrations for `doc_versions`, `books`, `nav_nodes`, `pages`, `sections`, `chunks`, and append-only `fetch_events`.
- Enforce page uniqueness by `doc_version_id` plus normalized path or URL.
- Store raw HTML, normalized URL, source metadata, content hash, parser version, fetch status, and timestamps.
- Add repository methods for versions/books, discovered navigation, page queues, fetch diagnostics, parsed sections, and chunks.
- Tests: migration smoke test, repository tests against local PostgreSQL, uniqueness tests, and append-only fetch event tests.

## Phase 3: Discovery and Fetching

- Implement URL normalization and source metadata helpers for Oracle PeopleBooks pages.
- Implement a conservative `httpx` fetcher with project user agent, low concurrency, delay, timeout, retries, and backoff.
- Do not enforce `robots.txt`.
- Implement `peoplebooks discover --version pt862 --book tpcr` to load the seed home/book navigation and queue pages in PostgreSQL.
- Current Phase 3 discovery uses the configured `tpcr` seed as a bootstrap and does not persist the higher-level Oracle home hierarchy above the book.
- Implement `peoplebooks status --version pt862` for discovered, queued, fetched, failed, parsed, and indexed counts.
- Tests: fixture parser tests for home/book HTML, mocked retry/backoff/timeout/hash/failure recording tests, and CLI discovery/status tests.

## Phase 4: Scraping, Parsing, and Reparse

- Implement `peoplebooks scrape --version pt862 --limit N` to process the next eligible pages, store raw HTML, record fetch events, and resume safely after interruption.
- Parse leaf pages from stored raw HTML into H1/H2/H3 sections and retrieval chunks with stable IDs and section paths.
- Track parser version on parsed content.
- Implement `peoplebooks reparse --version pt862 --parser-version X` to rebuild sections/chunks from stored raw HTML without refetching Oracle.
- Tests: fixture parser tests for leaf HTML, scrape `--limit` tests, resume tests, failed fetch tests, and reparse-without-network tests.

## Phase 5: Full-Text Indexing and Search

- Add PostgreSQL full-text vectors and indexes on chunks.
- Implement `peoplebooks index --version pt862` to populate or refresh chunk search vectors.
- Implement search repository methods returning version, book, page, section path, source URL, snippet, and stable IDs.
- Tests: indexing tests over known fixture content and search ranking/snippet tests.

## Phase 6: Read-Only MCP Server

- Implement `peoplebooks serve-mcp`.
- Add read-only MCP tools: `search_docs`, `get_page`, `get_section`, and `list_books`.
- Add MCP resources for versions, books, pages, and sections.
- Ensure MCP handlers only read PostgreSQL and never scrape live Oracle pages.
- Tests: MCP tool/resource response tests over known indexed content, including stable IDs and source metadata.

## Phase 7: End-to-End Validation and Maintenance

- Run the full flow locally: migrate database, discover `pt862/tpcr`, scrape a limited batch, parse, index, query through CLI/search, and query through MCP.
- Add concise README usage for local PostgreSQL setup, `uv` commands, CLI commands, and MCP startup.
- Update `AGENTS.md` whenever implementation details, dependencies, schema, CLI, MCP behavior, or architecture differ from the current instructions.
- Final tests: full pytest suite, CLI smoke run, database migration check, and MCP smoke test.

## Later: Full Products Tree Discovery

- Discover books by parsing the whole Oracle home `Products` tree instead of adding one seed URL per book.
- Persist intermediate navigation/category nodes from the actual Oracle tree, such as `Products` and the product-area/category nodes above each book.
- Treat PeopleCode API Reference (`tpcr`) as one discovered book in that tree; do not overwrite, duplicate, or special-case it when broad discovery is added.
- Preserve stable book codes and existing page identities when migrating from seed-only discovery to full-tree discovery.
- Tests: fixture coverage for nested home navigation, multiple discovered books, category parent chains, idempotent reruns, and preserving existing `tpcr` data.
