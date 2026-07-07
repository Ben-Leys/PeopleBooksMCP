from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from peoplebooks_mcp.scraper.oracle import NormalizedUrl, normalize_oracle_url


@dataclass(frozen=True, slots=True)
class BookLink:
    title: str
    normalized: NormalizedUrl
    source_url: str


@dataclass(frozen=True, slots=True)
class NavigationNode:
    stable_id: str
    title: str
    normalized: NormalizedUrl
    source_url: str
    position: int


def parse_home_books(html: str, *, base_url: str) -> dict[str, BookLink]:
    soup = BeautifulSoup(html, "lxml")
    books: dict[str, BookLink] = {}
    for anchor in soup.find_all("a", href=True):
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            continue
        source_url = _source_url(anchor["href"], base_url=base_url)
        normalized = normalize_oracle_url(source_url)
        if normalized.path.endswith(".html"):
            books[title] = BookLink(title=title, normalized=normalized, source_url=source_url)
    return books


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


def _stable_id(book_code: str, normalized_path: str) -> str:
    path = PurePosixPath(normalized_path)
    stem = path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return f"{book_code}/{slug}"


def _source_url(url: str, *, base_url: str) -> str:
    parsed = urlparse(urljoin(base_url, url))
    return urlunparse(parsed._replace(fragment=""))
