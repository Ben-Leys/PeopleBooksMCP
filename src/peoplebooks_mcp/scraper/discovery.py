from __future__ import annotations

from dataclasses import dataclass

from peoplebooks_mcp.config import BookSeed, DocVersionSeed
from peoplebooks_mcp.parser.navigation import BookLink, parse_book_navigation, parse_home_books
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.fetcher import PeopleBooksFetcher
from peoplebooks_mcp.scraper.oracle import normalize_oracle_url, oracle_source_metadata


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    nav_nodes_discovered: int
    pages_queued: int


class DiscoveryError(RuntimeError):
    pass


def discover_book(
    *,
    repository: PeopleBooksRepository,
    version_seed: DocVersionSeed,
    book_seed: BookSeed,
    fetcher: PeopleBooksFetcher,
) -> DiscoveryResult:
    home_fetch = fetcher.fetch(version_seed.seed_url)
    book_links = parse_home_books(home_fetch.text, base_url=version_seed.seed_url)
    book_source_url, book_normalized_url = _book_urls(
        book_links=book_links,
        version_seed=version_seed,
        book_seed=book_seed,
    )
    book_fetch = fetcher.fetch(book_source_url)

    version = repository.upsert_doc_version(
        code=version_seed.code,
        label=version_seed.label,
        seed_url=version_seed.seed_url,
        source_metadata=oracle_source_metadata(version_seed.seed_url),
    )
    book = repository.upsert_book(
        doc_version_id=version.id,
        code=book_seed.code,
        title=book_seed.title,
        seed_url=book_source_url,
        source_metadata=oracle_source_metadata(book_source_url),
    )
    root = repository.upsert_nav_node(
        doc_version_id=version.id,
        book_id=book.id,
        parent_id=None,
        stable_id=f"{book_seed.code}/root",
        title=book_seed.title,
        node_type="book",
        normalized_url=book_normalized_url,
        source_url=book_source_url,
        position=0,
        source_metadata=book_fetch.source_metadata | oracle_source_metadata(book_source_url),
    )

    nav_nodes = parse_book_navigation(
        book_fetch.text,
        base_url=book_source_url,
        book_code=book_seed.code,
    )
    for nav_node in nav_nodes:
        record = repository.upsert_nav_node(
            doc_version_id=version.id,
            book_id=book.id,
            parent_id=root.id,
            stable_id=nav_node.stable_id,
            title=nav_node.title,
            node_type="page",
            normalized_url=nav_node.normalized.url,
            source_url=nav_node.source_url,
            position=nav_node.position,
            source_metadata=oracle_source_metadata(nav_node.source_url),
        )
        repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            nav_node_id=record.id,
            normalized_url=nav_node.normalized.url,
            normalized_path=nav_node.normalized.path,
            source_url=nav_node.source_url,
            title=nav_node.title,
            source_metadata=oracle_source_metadata(nav_node.source_url),
        )

    return DiscoveryResult(nav_nodes_discovered=len(nav_nodes), pages_queued=len(nav_nodes))


def _book_urls(
    *,
    book_links: dict[str, BookLink],
    version_seed: DocVersionSeed,
    book_seed: BookSeed,
) -> tuple[str, str]:
    book_link = book_links.get(book_seed.title)
    if book_link is not None:
        return book_link.source_url, book_link.normalized.url

    configured_book_url = normalize_oracle_url(book_seed.seed_url)
    configured_home_url = normalize_oracle_url(version_seed.seed_url)
    if configured_book_url.url != configured_home_url.url:
        return book_seed.seed_url, configured_book_url.url

    raise DiscoveryError(
        f"Configured book {book_seed.title!r} was not found in {version_seed.seed_url}"
    )
