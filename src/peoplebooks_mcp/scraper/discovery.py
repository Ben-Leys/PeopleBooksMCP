from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from peoplebooks_mcp.config import BookSeed, DocVersionSeed
from peoplebooks_mcp.parser.navigation import (
    BookLink,
    ProductTreeNode,
    iter_product_books,
    parse_book_navigation,
    parse_home_books,
    parse_products_tree,
)
from peoplebooks_mcp.repositories import PeopleBooksRepository
from peoplebooks_mcp.scraper.fetcher import PeopleBooksFetcher
from peoplebooks_mcp.scraper.oracle import normalize_oracle_url, oracle_source_metadata


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    nav_nodes_discovered: int
    pages_queued: int
    books_discovered: int = 0


@dataclass(frozen=True, slots=True)
class DiscoveryProgress:
    books_processed: int
    total_books: int
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
    progress: Callable[[DiscoveryProgress], None] | None = None,
) -> DiscoveryResult:
    home_fetch = fetcher.fetch(version_seed.seed_url)
    products_tree = parse_products_tree(home_fetch.text, base_url=version_seed.seed_url)
    product_book = _find_product_book(
        products_tree=products_tree,
        book_code=book_seed.code,
        title=book_seed.title,
    )
    if product_book is not None:
        return _discover_product_books(
            repository=repository,
            version_seed=version_seed,
            fetcher=fetcher,
            product_books=[product_book],
            progress=progress,
        )

    book_links = parse_home_books(home_fetch.text, base_url=version_seed.seed_url)
    book_source_url, book_normalized_url = _book_urls(
        book_links=book_links,
        version_seed=version_seed,
        book_seed=book_seed,
    )
    _report_discovery_progress(
        progress=progress,
        books_processed=0,
        total_books=1,
        nav_nodes_discovered=0,
        pages_queued=0,
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

    result = DiscoveryResult(
        nav_nodes_discovered=len(nav_nodes) + 1,
        pages_queued=len(nav_nodes),
        books_discovered=1,
    )
    _report_discovery_progress(
        progress=progress,
        books_processed=1,
        total_books=1,
        nav_nodes_discovered=result.nav_nodes_discovered,
        pages_queued=result.pages_queued,
    )
    return result


def discover_products_tree(
    *,
    repository: PeopleBooksRepository,
    version_seed: DocVersionSeed,
    fetcher: PeopleBooksFetcher,
    book_codes: set[str] | None = None,
    progress: Callable[[DiscoveryProgress], None] | None = None,
) -> DiscoveryResult:
    home_fetch = fetcher.fetch(version_seed.seed_url)
    products_tree = parse_products_tree(home_fetch.text, base_url=version_seed.seed_url)
    product_books = [
        book
        for book in iter_product_books(products_tree)
        if book.book_code is not None and (book_codes is None or book.book_code in book_codes)
    ]
    if not product_books:
        if book_codes:
            requested = ", ".join(sorted(book_codes))
            raise DiscoveryError(f"Book code(s) not found in Products tree: {requested}")
        raise DiscoveryError(f"No books were found in Products tree at {version_seed.seed_url}")

    return _discover_product_books(
        repository=repository,
        version_seed=version_seed,
        fetcher=fetcher,
        product_books=product_books,
        progress=progress,
    )


def _discover_product_books(
    *,
    repository: PeopleBooksRepository,
    version_seed: DocVersionSeed,
    fetcher: PeopleBooksFetcher,
    product_books: list[ProductTreeNode],
    progress: Callable[[DiscoveryProgress], None] | None = None,
) -> DiscoveryResult:
    version = repository.upsert_doc_version(
        code=version_seed.code,
        label=version_seed.label,
        seed_url=version_seed.seed_url,
        source_metadata=oracle_source_metadata(version_seed.seed_url),
    )

    discovered_nav_nodes = 0
    queued_pages = 0
    discovered_books = 0
    _report_discovery_progress(
        progress=progress,
        books_processed=discovered_books,
        total_books=len(product_books),
        nav_nodes_discovered=discovered_nav_nodes,
        pages_queued=queued_pages,
    )
    for product_book in product_books:
        if (
            product_book.book_code is None
            or product_book.source_url is None
            or product_book.normalized is None
        ):
            continue

        book_fetch = fetcher.fetch(product_book.source_url)
        book = repository.upsert_book(
            doc_version_id=version.id,
            code=product_book.book_code,
            title=product_book.title,
            seed_url=product_book.source_url,
            source_metadata=oracle_source_metadata(product_book.source_url),
        )
        parent_id = _upsert_category_chain(
            repository=repository,
            doc_version_id=version.id,
            book_id=book.id,
            book_code=product_book.book_code,
            category_path=product_book.category_path,
            version_seed=version_seed,
        )
        discovered_nav_nodes += len(product_book.category_path)

        root = repository.upsert_nav_node(
            doc_version_id=version.id,
            book_id=book.id,
            parent_id=parent_id,
            stable_id=f"{product_book.book_code}/root",
            title=product_book.title,
            node_type="book",
            normalized_url=product_book.normalized.url,
            source_url=product_book.source_url,
            position=product_book.position,
            source_metadata=book_fetch.source_metadata
            | oracle_source_metadata(product_book.source_url),
        )
        discovered_nav_nodes += 1

        nav_nodes = parse_book_navigation(
            book_fetch.text,
            base_url=product_book.source_url,
            book_code=product_book.book_code,
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

        discovered_books += 1
        discovered_nav_nodes += len(nav_nodes)
        queued_pages += len(nav_nodes)
        _report_discovery_progress(
            progress=progress,
            books_processed=discovered_books,
            total_books=len(product_books),
            nav_nodes_discovered=discovered_nav_nodes,
            pages_queued=queued_pages,
        )

    return DiscoveryResult(
        nav_nodes_discovered=discovered_nav_nodes,
        pages_queued=queued_pages,
        books_discovered=discovered_books,
    )


def _report_discovery_progress(
    *,
    progress: Callable[[DiscoveryProgress], None] | None,
    books_processed: int,
    total_books: int,
    nav_nodes_discovered: int,
    pages_queued: int,
) -> None:
    if progress is None:
        return
    progress(
        DiscoveryProgress(
            books_processed=books_processed,
            total_books=total_books,
            nav_nodes_discovered=nav_nodes_discovered,
            pages_queued=pages_queued,
        )
    )


def _upsert_category_chain(
    *,
    repository: PeopleBooksRepository,
    doc_version_id: int,
    book_id: int,
    book_code: str,
    category_path: tuple[ProductTreeNode, ...],
    version_seed: DocVersionSeed,
) -> int | None:
    parent_id: int | None = None
    for category in category_path:
        source_url = category.source_url
        record = repository.upsert_nav_node(
            doc_version_id=doc_version_id,
            book_id=book_id,
            parent_id=parent_id,
            stable_id=f"{book_code}/{category.stable_id}",
            title=category.title,
            node_type="category",
            normalized_url=category.normalized.url if category.normalized is not None else None,
            source_url=source_url,
            position=category.position,
            source_metadata=oracle_source_metadata(source_url or version_seed.seed_url),
        )
        parent_id = record.id

    return parent_id


def _find_product_book(
    *,
    products_tree: ProductTreeNode,
    book_code: str,
    title: str,
) -> ProductTreeNode | None:
    for product_book in iter_product_books(products_tree):
        if product_book.book_code == book_code or product_book.title == title:
            return product_book
    return None


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
