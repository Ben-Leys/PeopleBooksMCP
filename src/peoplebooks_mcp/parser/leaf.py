from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

JsonObject = dict[str, Any]

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}
BLOCK_TAGS = {"p", "li", "pre", "td", "th", "dt", "dd"}
IGNORED_TAGS = {"script", "style", "nav", "header", "footer", "noscript"}


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    stable_id: str
    ordinal: int
    content: str
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class ParsedSection:
    stable_id: str
    heading: str
    level: int
    section_path: tuple[str, ...]
    ordinal: int
    content: str
    chunks: tuple[ParsedChunk, ...]
    source_metadata: JsonObject


@dataclass(slots=True)
class _MutableSection:
    stable_id: str
    heading: str
    level: int
    section_path: tuple[str, ...]
    ordinal: int
    blocks: list[str]
    source_metadata: JsonObject


def parse_leaf_page(html: str, *, page_stable_id: str) -> list[ParsedSection]:
    """Parse a PeopleBooks leaf page into heading sections and retrieval chunks."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(IGNORED_TAGS):
        tag.decompose()

    container = _content_container(soup)
    sections: list[_MutableSection] = []
    heading_stack: dict[int, str] = {}
    slug_counts: dict[str, int] = {}
    preface_blocks: list[str] = []
    current: _MutableSection | None = None

    for tag in container.find_all([*HEADING_LEVELS, *BLOCK_TAGS]):
        if not isinstance(tag, Tag) or _inside_same_kind_block(tag):
            continue

        name = tag.name.lower()
        text = _heading_text(tag) if name in HEADING_LEVELS else _block_text(tag)
        if not text:
            continue

        if name in HEADING_LEVELS:
            level = HEADING_LEVELS[name]
            heading_stack = {
                stack_level: heading
                for stack_level, heading in heading_stack.items()
                if stack_level < level
            }
            heading_stack[level] = text
            section_path = tuple(
                heading_stack[stack_level] for stack_level in sorted(heading_stack)
            )
            stable_id = _section_stable_id(
                page_stable_id=page_stable_id,
                section_path=section_path,
                slug_counts=slug_counts,
                ordinal=len(sections),
            )
            current = _MutableSection(
                stable_id=stable_id,
                heading=text,
                level=level,
                section_path=section_path,
                ordinal=len(sections),
                blocks=[],
                source_metadata={"tag": name},
            )
            if preface_blocks:
                current.blocks.extend(preface_blocks)
                preface_blocks = []
            sections.append(current)
            continue

        if current is None:
            preface_blocks.append(text)
        else:
            current.blocks.append(text)

    if not sections:
        title = _page_title(soup)
        sections.append(
            _MutableSection(
                stable_id=_section_stable_id(
                    page_stable_id=page_stable_id,
                    section_path=(title,),
                    slug_counts=slug_counts,
                    ordinal=0,
                ),
                heading=title,
                level=1,
                section_path=(title,),
                ordinal=0,
                blocks=preface_blocks,
                source_metadata={"tag": "title"},
            )
        )

    return [_freeze_section(section) for section in sections]


def _freeze_section(section: _MutableSection) -> ParsedSection:
    content = "\n\n".join(section.blocks)
    chunks: tuple[ParsedChunk, ...]
    if content:
        chunks = (
            ParsedChunk(
                stable_id=f"{section.stable_id}/chunk-0",
                ordinal=0,
                content=content,
                metadata={
                    "section_heading": section.heading,
                    "section_path": list(section.section_path),
                },
            ),
        )
    else:
        chunks = ()

    return ParsedSection(
        stable_id=section.stable_id,
        heading=section.heading,
        level=section.level,
        section_path=section.section_path,
        ordinal=section.ordinal,
        content=content,
        chunks=chunks,
        source_metadata=section.source_metadata,
    )


def _content_container(soup: BeautifulSoup) -> Tag:
    for selector in ("main", "article", "body"):
        tag = soup.find(selector)
        if isinstance(tag, Tag):
            return tag
    return soup


def _inside_same_kind_block(tag: Tag) -> bool:
    if tag.name.lower() not in BLOCK_TAGS:
        return False
    parent = tag.parent
    while isinstance(parent, Tag):
        if parent.name.lower() in BLOCK_TAGS:
            return True
        parent = parent.parent
    return False


def _section_stable_id(
    *,
    page_stable_id: str,
    section_path: tuple[str, ...],
    slug_counts: dict[str, int],
    ordinal: int,
) -> str:
    slug = "-".join(part_slug for part in section_path if (part_slug := _slugify(part)))
    if not slug:
        slug = f"section-{ordinal + 1}"
    slug_counts[slug] = slug_counts.get(slug, 0) + 1
    if slug_counts[slug] > 1:
        slug = f"{slug}-{slug_counts[slug]}"
    return f"{page_stable_id}/{slug}"


def _page_title(soup: BeautifulSoup) -> str:
    if soup.title is not None:
        title = _clean_text(soup.title.get_text(" ", strip=True))
        if title:
            return title
    return "Untitled Page"


def _heading_text(tag: Tag) -> str:
    return _clean_text(tag.get_text(" ", strip=True))


def _block_text(tag: Tag) -> str:
    if tag.name.lower() == "pre":
        return _clean_pre_text(tag.get_text())
    return _clean_text(tag.get_text(" ", strip=True))


def _clean_pre_text(text: str) -> str:
    lines = textwrap.dedent(text).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
