# Current review findings

Reviewed against the full project and the populated PeopleTools 8.62 database on 2026-07-11.
The earlier findings for Markdown chunking and continuation, indexed relaxed search, compact MCP
responses, structured-only compatibility, indexed `find_pages`, shared search timeouts, automatic
post-parse indexing, explicit lifecycle-state labels, and MCP input schemas have been implemented
and were removed from this active list.

## Current verdict

The normal MCP path is substantially better. The database contains 4,762 indexed pages, 43,798
sections, and 48,707 chunks. Chunks are capped at 2,000 characters, heading-only sections are
searchable, section content is losslessly pageable, and ordinary strict searches returned five
page-diversified results in roughly 0.01-0.05 seconds during this review. A real stdio MCP client
successfully initialized the server, listed all six tools, and received structured search results.

The server is useful now for common lexical searches and exact identifier lookups. It is not yet
consistently fast or relevant for every natural-language request: the remaining search paths below
can still take several seconds or hit the configured timeout.

## 1. Fix the remaining slow and weak search paths

`search_docs` strict English FTS is fast, but two paths still need live-sized optimization:

- Relaxed search took 1.6-2.3 seconds for two sampled questions and exceeded 10 seconds for the
  useful query `What is the difference between CreateArray and CreateArrayRept?`.
- Exact identifier searches took roughly 0.6-1.1 seconds. This is usable, but slower than necessary
  because exact search scans chunk content instead of starting from indexed identifier candidates.

Recommended changes:

- Inspect `EXPLAIN (ANALYZE, BUFFERS)` for relaxed identifier queries. Avoid an `ANY(...)` or
  trigram predicate shape that prevents the GIN index from bounding candidates.
- Add live-sized performance/relevance regression tests for prose questions, camel-case APIs,
  paired identifiers, no-result queries, and `find_pages`.

## 2. Finish the single-worker ingestion lifecycle

Concurrent scraper claiming is intentionally out of scope because this deployment will run only one
scraper. The remaining lifecycle issues still matter with one worker:

- Failed pages are terminal because the scrape queue only selects `queued` pages and fetched pages
  awaiting parsing. There is no retry/requeue command for transient failures.
- `PeopleBooksFetcher.fetch` creates and closes an `httpx.Client` for every URL. Reusing one client
  for a discovery or scrape run would reuse connections and TLS sessions.

Recommended changes:

- Add an explicit `retry-failed`/`requeue-failed` command with bounded retry metadata.
- Make the fetcher a context-managed run-level client while retaining the existing conservative
  delay and retry behavior.

## 3. Polish the MCP contract

- The stdio initialization response reports the MCP SDK version (`1.28.1` during this review) as the
  PeopleBooks server version. Advertise the project version instead.
- The six-tool catalog serializes to about 17,086 characters. The tool set is appropriate, but
  further concise descriptions may make those tokens more useful.
- Add one automated end-to-end stdio protocol test. Current MCP tests call FastMCP in process; the
  manual stdio smoke test passed on Windows during this review.

## 4. Configuration, packaging, and operational hardening

- Documentation versions and the initial `tpcr` seed are still Python constants. TOML currently
  accepts only `[settings]`, so adding another documentation version is a small code/configuration
  change rather than a data-only addition.
- The official MCP Python SDK says packages using stable v1 should add a `<2` upper bound before the
  stable v2 release. Change the dependency to a tested v1 range such as `mcp>=1.28,<2` and refresh
  the lockfile.
- The wheel target includes only `src/peoplebooks_mcp`; Alembic configuration and migrations are not
  bundled. Either document that the server is repo-operated only or package the migration assets so
  an installed wheel can initialize its database.
- MCP annotations describe read-only behavior but do not enforce database permissions. Production
  MCP processes should use a PostgreSQL role restricted to `SELECT` plus a role-level statement
  timeout.
- There is still no CI workflow, license, or security policy. These are release/maintenance items,
  not blockers for local use.

Official SDK guidance: https://github.com/modelcontextprotocol/python-sdk

## 5. Code hygiene

- `ruff check` and compilation pass, and all 99 tests pass serially.
- `ruff format --check` still reports three untouched files needing formatting:
  `config.py`, `repositories/__init__.py`, and `test_config.py`.
- `mcp_server.py` and `repositories/postgres.py` are large. Splitting them by tool/resource payloads
  and ingestion/search repositories would improve maintainability, but this is refactoring rather
  than a current correctness requirement.
