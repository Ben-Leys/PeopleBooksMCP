from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from peoplebooks_mcp.scraper.oracle import NormalizedUrl, normalize_oracle_url


@dataclass(frozen=True, slots=True)
class BookLink:
    title: str
    normalized: NormalizedUrl
    source_url: str
    book_code: str | None = None
    category_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductTreeNode:
    stable_id: str
    title: str
    node_type: str
    position: int
    normalized: NormalizedUrl | None = None
    source_url: str | None = None
    book_code: str | None = None
    category_path: tuple[ProductTreeNode, ...] = ()
    children: tuple[ProductTreeNode, ...] = ()


@dataclass(frozen=True, slots=True)
class NavigationNode:
    stable_id: str
    title: str
    normalized: NormalizedUrl
    source_url: str
    position: int


@dataclass(frozen=True, slots=True)
class _NodeLabel:
    title: str
    href: str | None


def parse_home_books(html: str, *, base_url: str) -> dict[str, BookLink]:
    tree = parse_products_tree(html, base_url=base_url)
    product_books = {
        book.title: BookLink(
            title=book.title,
            normalized=book.normalized,
            source_url=book.source_url,
            book_code=book.book_code,
            category_path=tuple(category.title for category in book.category_path),
        )
        for book in iter_product_books(tree)
        if book.normalized is not None and book.source_url is not None
    }
    if product_books:
        return product_books

    soup = BeautifulSoup(html, "lxml")
    books: dict[str, BookLink] = {}
    for anchor in soup.find_all("a", href=True):
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            continue
        source_url = _source_url(anchor["href"], base_url=base_url)
        normalized = normalize_oracle_url(source_url)
        if normalized.path.endswith(".html"):
            books[title] = BookLink(
                title=title,
                normalized=normalized,
                source_url=source_url,
                book_code=_book_code(source_url=source_url, normalized=normalized),
            )
    return books


def parse_products_tree(html: str, *, base_url: str) -> ProductTreeNode:
    soup = BeautifulSoup(html, "lxml")
    container = soup.find(id="contents") or soup.body or soup
    product_list = _first_child_list(container) or _first_descendant_list(container)
    products_item = _find_products_item(product_list)
    source_url: str | None = None
    normalized: NormalizedUrl | None = None

    if products_item is not None:
        label = _node_label(products_item)
        if label.href is not None:
            source_url = _source_url(label.href, base_url=base_url)
            normalized = normalize_oracle_url(source_url)
        product_list = _first_child_list(products_item)
    else:
        product_list = None

    root_path_node = ProductTreeNode(
        stable_id="products",
        title="Products",
        node_type="category",
        normalized=normalized,
        source_url=source_url,
        position=0,
    )
    children = (
        _parse_product_list(
            product_list,
            parent_stable_id=root_path_node.stable_id,
            category_path=(root_path_node,),
            base_url=base_url,
        )
        if product_list is not None
        else []
    )
    return replace(root_path_node, children=tuple(children))


def iter_product_books(node: ProductTreeNode) -> Iterator[ProductTreeNode]:
    if node.node_type == "book":
        yield node
    for child in node.children:
        yield from iter_product_books(child)


def parse_book_navigation(html: str, *, base_url: str, book_code: str) -> list[NavigationNode]:
    soup = BeautifulSoup(html, "lxml")
    nodes: list[NavigationNode] = []
    seen: set[str] = set()
    book_path_marker = f"/{book_code}/"

    for anchor in soup.find_all("a", href=True):
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            continue

        source_url = _source_url(anchor["href"], base_url=base_url)
        normalized = normalize_oracle_url(source_url)
        if book_path_marker not in normalized.path or not normalized.path.endswith(".html"):
            continue
        if normalized.path in seen:
            continue

        seen.add(normalized.path)
        nodes.append(
            NavigationNode(
                stable_id=_stable_id(book_code, normalized.path),
                title=title,
                normalized=normalized,
                source_url=source_url,
                position=len(nodes),
            )
        )

    return nodes


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_product_list(
    list_tag: Tag,
    *,
    parent_stable_id: str,
    category_path: tuple[ProductTreeNode, ...],
    base_url: str,
) -> list[ProductTreeNode]:
    nodes: list[ProductTreeNode] = []
    seen_stable_ids: set[str] = set()

    for position, item in enumerate(_direct_list_items(list_tag)):
        label = _node_label(item)
        if not label.title:
            continue

        source_url: str | None = None
        normalized: NormalizedUrl | None = None
        if label.href is not None:
            source_url = _source_url(label.href, base_url=base_url)
            normalized = normalize_oracle_url(source_url)

        child_list = _first_child_list(item)
        is_book = (
            normalized is not None and normalized.path.endswith(".html") and child_list is None
        )
        if is_book:
            book_code = _book_code(source_url=source_url, normalized=normalized)
            nodes.append(
                ProductTreeNode(
                    stable_id=f"{book_code}/root",
                    title=label.title,
                    node_type="book",
                    normalized=normalized,
                    source_url=source_url,
                    book_code=book_code,
                    category_path=category_path,
                    position=position,
                )
            )
            continue

        stable_id = _category_stable_id(
            parent_stable_id=parent_stable_id,
            title=label.title,
            seen_stable_ids=seen_stable_ids,
        )
        path_node = ProductTreeNode(
            stable_id=stable_id,
            title=label.title,
            node_type="category",
            normalized=normalized,
            source_url=source_url,
            category_path=category_path,
            position=position,
        )
        children = (
            _parse_product_list(
                child_list,
                parent_stable_id=stable_id,
                category_path=category_path + (path_node,),
                base_url=base_url,
            )
            if child_list is not None
            else []
        )
        nodes.append(replace(path_node, children=tuple(children)))

    return nodes


def _direct_list_items(list_tag: Tag) -> Iterator[Tag]:
    for child in list_tag.children:
        if isinstance(child, Tag) and child.name == "li":
            yield child


def _find_products_item(list_tag: Tag | None) -> Tag | None:
    if list_tag is None:
        return None

    for item in _direct_list_items(list_tag):
        if _node_label(item).title.casefold() == "products":
            return item
    return None


def _node_label(item: Tag) -> _NodeLabel:
    text_parts: list[str] = []
    for child in item.children:
        if isinstance(child, Tag) and child.name in {"ul", "ol"}:
            break
        if isinstance(child, Tag) and child.name == "a" and child.get("href"):
            return _NodeLabel(
                title=_clean_text(child.get_text(" ", strip=True)),
                href=child["href"],
            )
        if isinstance(child, Tag):
            nested_anchor = child.find("a", href=True)
            if isinstance(nested_anchor, Tag):
                return _NodeLabel(
                    title=_clean_text(nested_anchor.get_text(" ", strip=True)),
                    href=nested_anchor["href"],
                )
            text_parts.append(child.get_text(" ", strip=True))
            continue
        if isinstance(child, NavigableString):
            text_parts.append(str(child))

    return _NodeLabel(title=_clean_text(" ".join(text_parts)), href=None)


def _first_child_list(tag: Tag) -> Tag | None:
    for child in tag.children:
        if isinstance(child, Tag) and child.name in {"ul", "ol"}:
            return child
    return None


def _first_descendant_list(tag: Tag) -> Tag | None:
    descendant = tag.find(["ul", "ol"])
    return descendant if isinstance(descendant, Tag) else None


def _category_stable_id(
    *,
    parent_stable_id: str,
    title: str,
    seen_stable_ids: set[str],
) -> str:
    slug = _slug(title) or "category"
    stable_id = f"{parent_stable_id}/{slug}"
    if stable_id not in seen_stable_ids:
        seen_stable_ids.add(stable_id)
        return stable_id

    suffix = 2
    while f"{stable_id}_{suffix}" in seen_stable_ids:
        suffix += 1
    suffixed = f"{stable_id}_{suffix}"
    seen_stable_ids.add(suffixed)
    return suffixed


def _stable_id(book_code: str, normalized_path: str) -> str:
    path = PurePosixPath(normalized_path)
    stem = path.stem.lower()
    slug = _slug(stem)
    return f"{book_code}/{slug}"


def _book_code(*, source_url: str, normalized: NormalizedUrl) -> str:
    query = parse_qs(urlparse(source_url).query)
    focusnode = query.get("focusnode", [""])[0]
    candidate = focusnode or PurePosixPath(normalized.path).stem
    return _slug(candidate).lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _source_url(url: str, *, base_url: str) -> str:
    parsed = urlparse(urljoin(base_url, url))
    return urlunparse(parsed._replace(fragment=""))
