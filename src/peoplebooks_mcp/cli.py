from typing import Annotated

import typer

from peoplebooks_mcp.config import load_config

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
) -> None:
    """Discover and queue PeopleBooks pages for a configured book."""
    config = load_config()
    if version not in config.doc_versions or book not in config.books:
        typer.echo(f"Unknown seed configuration: version={version!r}, book={book!r}")
        raise typer.Exit(code=2)
    _not_implemented("discover")


@app.command()
def scrape(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
    limit: Annotated[int, typer.Option(help="Maximum pages to scrape.", min=1)] = 25,
) -> None:
    """Fetch queued PeopleBooks pages into PostgreSQL."""
    if not version or limit < 1:
        raise typer.Exit(code=2)
    _not_implemented("scrape")


@app.command()
def status(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
) -> None:
    """Show scrape and indexing status for a documentation version."""
    if not version:
        raise typer.Exit(code=2)
    _not_implemented("status")


@app.command()
def reparse(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
    parser_version: Annotated[str, typer.Option(help="Parser version to write.")] = "v1",
) -> None:
    """Rebuild parsed sections and chunks from stored raw HTML."""
    if not version or not parser_version:
        raise typer.Exit(code=2)
    _not_implemented("reparse")


@app.command()
def index(
    version: Annotated[str, typer.Option(help="Documentation version key.")] = "pt862",
) -> None:
    """Populate PostgreSQL full-text search vectors."""
    if not version:
        raise typer.Exit(code=2)
    _not_implemented("index")


@app.command(name="serve-mcp")
def serve_mcp() -> None:
    """Start the read-only MCP server."""
    _not_implemented("serve-mcp")
