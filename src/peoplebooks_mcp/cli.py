from typing import Annotated

import typer

from peoplebooks_mcp.config import load_config
from peoplebooks_mcp.indexing import index_pages
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.discovery import DiscoveryError, discover_book, discover_products_tree
from peoplebooks_mcp.scraper.fetcher import FetchError, PeopleBooksFetcher
from peoplebooks_mcp.scraper.scrape import reparse_pages, scrape_pages

app = typer.Typer(
    help="Scrape Oracle PeopleBooks into PostgreSQL and serve read-only MCP docs.",
    no_args_is_help=True,
)


def _not_implemented(command: str) -> None:
    typer.echo(f"{command} is planned for a later implementation phase.")
    raise typer.Exit(code=1)


@app.command()
def discover(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
    book: Annotated[str, typer.Option(help="Book key to discover.")] = "tpcr",
    all_books: Annotated[
        bool,
        typer.Option("--all-books", help="Discover every book found in the Oracle Products tree."),
    ] = False,
) -> None:
    """Discover and queue PeopleBooks pages."""
    config = load_config()
    if version not in config.doc_versions:
        typer.echo(f"Unknown seed configuration: version={version!r}")
        raise typer.Exit(code=2)
    if all_books and book != "tpcr":
        typer.echo("--book cannot be combined with --all-books")
        raise typer.Exit(code=2)

    version_seed = config.doc_versions[version]
    book_seed = config.books.get(book)
    if not all_books:
        if book_seed is None:
            typer.echo(f"Unknown seed configuration: version={version!r}, book={book!r}")
            raise typer.Exit(code=2)
        if book_seed.version != version_seed.code:
            typer.echo(f"Book {book!r} is not configured for version {version!r}")
            raise typer.Exit(code=2)

    fetcher = PeopleBooksFetcher(
        user_agent=config.settings.user_agent,
        timeout_seconds=config.settings.request_timeout_seconds,
    )
    try:
        with PeopleBooksRepository.connect(config.settings.database_url) as repository:
            if all_books:
                result = discover_products_tree(
                    repository=repository,
                    version_seed=version_seed,
                    fetcher=fetcher,
                    book_codes=None,
                )
            else:
                result = discover_book(
                    repository=repository,
                    version_seed=version_seed,
                    book_seed=book_seed,
                    fetcher=fetcher,
                )
    except (DiscoveryError, FetchError) as error:
        typer.echo(f"Discovery failed: {error}")
        raise typer.Exit(code=1) from error

    if all_books:
        typer.echo(
            f"Discovered {result.books_discovered} books; "
            f"{result.nav_nodes_discovered} navigation nodes; "
            f"queued {result.pages_queued} pages."
        )
    else:
        typer.echo(
            f"Discovered {result.nav_nodes_discovered} navigation nodes; "
            f"queued {result.pages_queued} pages."
        )


@app.command()
def scrape(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
    limit: Annotated[int, typer.Option(help="Maximum pages to scrape.", min=1)] = 25,
) -> None:
    """Fetch queued PeopleBooks pages into PostgreSQL."""
    if not version or limit < 1:
        raise typer.Exit(code=2)
    config = load_config()
    fetcher = PeopleBooksFetcher(
        user_agent=config.settings.user_agent,
        timeout_seconds=config.settings.request_timeout_seconds,
    )
    try:
        with PeopleBooksRepository.connect(config.settings.database_url) as repository:
            result = scrape_pages(
                repository=repository,
                version_code=version,
                fetcher=fetcher,
                limit=limit,
            )
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(code=2) from error

    typer.echo(f"Scraped {result.scraped} pages; failed {result.failed}; parsed {result.parsed}.")


@app.command()
def status(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
) -> None:
    """Show scrape and indexing status for a documentation version."""
    if not version:
        raise typer.Exit(code=2)
    config = load_config()
    with PeopleBooksRepository.connect(config.settings.database_url) as repository:
        doc_version = repository.get_doc_version_by_code(version)
        if doc_version is None:
            typer.echo(f"Unknown discovered version: {version!r}")
            raise typer.Exit(code=2)
        counts = repository.get_status_counts(doc_version_id=doc_version.id)

    typer.echo(f"discovered: {counts.discovered}")
    typer.echo(f"queued: {counts.queued}")
    typer.echo(f"fetched: {counts.fetched}")
    typer.echo(f"failed: {counts.failed}")
    typer.echo(f"parsed: {counts.parsed}")
    typer.echo(f"indexed: {counts.indexed}")


@app.command()
def reparse(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
    parser_version: Annotated[str, typer.Option(help="Parser version to write.")] = "v1",
) -> None:
    """Rebuild parsed sections and chunks from stored raw HTML."""
    if not version or not parser_version:
        raise typer.Exit(code=2)
    config = load_config()
    try:
        with PeopleBooksRepository.connect(config.settings.database_url) as repository:
            result = reparse_pages(
                repository=repository,
                version_code=version,
                parser_version=parser_version,
            )
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(code=2) from error

    typer.echo(f"Reparsed {result.reparsed} pages.")


@app.command()
def index(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
) -> None:
    """Populate PostgreSQL full-text search vectors."""
    if not version:
        raise typer.Exit(code=2)
    config = load_config()
    try:
        with PeopleBooksRepository.connect(config.settings.database_url) as repository:
            result = index_pages(repository=repository, version_code=version)
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(code=2) from error

    typer.echo(f"Indexed {result.indexed_chunks} chunks across {result.indexed_pages} pages.")


@app.command(name="serve-mcp")
def serve_mcp() -> None:
    """Start the read-only MCP server."""
    _not_implemented("serve-mcp")
