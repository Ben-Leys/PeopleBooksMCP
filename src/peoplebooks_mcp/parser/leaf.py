from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

JsonObject = dict[str, Any]

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}
BLOCK_TAGS = {"p", "pre", "ul", "ol", "table", "dl", "blockquote"}
IGNORED_TAGS = {"script", "style", "nav", "header", "footer", "noscript"}
TARGET_CHUNK_CHARS = 1600
MAX_CHUNK_CHARS = 2000
ADMONITION_WORDS = ("warning", "caution", "important", "note", "tip")


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


@dataclass(frozen=True, slots=True)
class _MarkdownBlock:
    content: str
    kind: str


@dataclass(slots=True)
class _MutableSection:
    stable_id: str
    heading: str
    level: int
    section_path: tuple[str, ...]
    ordinal: int
    blocks: list[_MarkdownBlock]
    source_metadata: JsonObject


def parse_leaf_page(html: str, *, page_stable_id: str) -> list[ParsedSection]:
    """Parse a PeopleBooks leaf page into Markdown sections and semantic chunks."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(IGNORED_TAGS):
        tag.decompose()

    container = _content_container(soup)
    sections: list[_MutableSection] = []
    heading_stack: dict[int, str] = {}
    slug_counts: dict[str, int] = {}
    preface_blocks: list[_MarkdownBlock] = []
    current: _MutableSection | None = None

    for tag in container.find_all([*HEADING_LEVELS, *BLOCK_TAGS, "div", "aside"]):
        if not isinstance(tag, Tag) or _inside_rendered_block(tag):
            continue

        name = tag.name.lower()
        if name in {"div", "aside"} and not _is_admonition(tag):
            continue
        if name in HEADING_LEVELS:
            text = _heading_text(tag)
            if not text:
                continue
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
                source_metadata={"tag": name, "content_format": "markdown"},
            )
            if preface_blocks:
                current.blocks.extend(preface_blocks)
                preface_blocks = []
            sections.append(current)
            continue

        block = _render_block(tag)
        if block is None:
            continue
        if current is None:
            preface_blocks.append(block)
        else:
            current.blocks.append(block)

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
                source_metadata={"tag": "title", "content_format": "markdown"},
            )
        )

    return [_freeze_section(section) for section in sections]


def _freeze_section(section: _MutableSection) -> ParsedSection:
    content = "\n\n".join(block.content for block in section.blocks)
    chunk_blocks = _semantic_chunks(section.blocks)
    if not chunk_blocks:
        # Search vectors also include the section heading/path, while this small body gives
        # heading-only matches a useful snippet through the existing chunk search pipeline.
        chunk_blocks = [section.heading]
    chunks = tuple(
        ParsedChunk(
            stable_id=f"{section.stable_id}/chunk-{ordinal}",
            ordinal=ordinal,
            content=chunk_content,
            metadata={
                "section_heading": section.heading,
                "section_path": list(section.section_path),
                "content_format": "markdown",
                "heading_only": not bool(content),
            },
        )
        for ordinal, chunk_content in enumerate(chunk_blocks)
    )

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


def _semantic_chunks(blocks: list[_MarkdownBlock]) -> list[str]:
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(_split_oversized_block(block))

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for piece in pieces:
        separator = 2 if current else 0
        proposed_length = current_length + separator + len(piece)
        if current and proposed_length > MAX_CHUNK_CHARS:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0
            separator = 0
        current.append(piece)
        current_length += separator + len(piece)
        if current_length >= TARGET_CHUNK_CHARS:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_oversized_block(block: _MarkdownBlock) -> list[str]:
    if len(block.content) <= MAX_CHUNK_CHARS:
        return [block.content]
    if block.kind in {"code", "table"}:
        lines = block.content.splitlines(keepends=True)
        return _split_lines_losslessly(lines)

    paragraphs = re.split(r"(?<=[.!?])\s+", block.content)
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        separator = " " if current else ""
        if current and len(current) + len(separator) + len(paragraph) > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = ""
            separator = ""
        if len(paragraph) > MAX_CHUNK_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_text_losslessly(paragraph))
        else:
            current += separator + paragraph
    if current:
        pieces.append(current)
    return pieces


def _split_lines_losslessly(lines: list[str]) -> list[str]:
    pieces: list[str] = []
    current = ""
    for line in lines:
        if current and len(current) + len(line) > MAX_CHUNK_CHARS:
            pieces.append(current.rstrip("\n"))
            current = ""
        if len(line) > MAX_CHUNK_CHARS:
            if current:
                pieces.append(current.rstrip("\n"))
                current = ""
            pieces.extend(_split_text_losslessly(line.rstrip("\n")))
        else:
            current += line
    if current:
        pieces.append(current.rstrip("\n"))
    return pieces


def _split_text_losslessly(text: str) -> list[str]:
    return [
        text[offset : offset + MAX_CHUNK_CHARS] for offset in range(0, len(text), MAX_CHUNK_CHARS)
    ]


def _content_container(soup: BeautifulSoup) -> Tag:
    for selector in ("main", "article", "body"):
        tag = soup.find(selector)
        if isinstance(tag, Tag):
            return tag
    return soup


def _inside_rendered_block(tag: Tag) -> bool:
    parent = tag.parent
    while isinstance(parent, Tag):
        if parent.name.lower() in BLOCK_TAGS or _is_admonition(parent):
            return True
        parent = parent.parent
    return False


def _is_admonition(tag: Tag) -> bool:
    if tag.name.lower() not in {"div", "p", "aside"}:
        return False
    labels = " ".join([*tag.get("class", []), str(tag.get("role", ""))]).lower()
    return any(word in labels for word in ADMONITION_WORDS)


def _render_block(tag: Tag) -> _MarkdownBlock | None:
    name = tag.name.lower()
    if _is_admonition(tag):
        label = next(
            (
                word.title()
                for word in ADMONITION_WORDS
                if word in " ".join(tag.get("class", [])).lower()
            ),
            "Note",
        )
        body = _render_children(tag)
        content = f"> **{label}:** {body}" if body else f"> **{label}:**"
        return _MarkdownBlock(content=content.replace("\n", "\n> "), kind="admonition")
    if name == "pre":
        code = _clean_pre_text(tag.get_text())
        if not code:
            return None
        longest_ticks = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest_ticks + 1)
        return _MarkdownBlock(content=f"{fence}\n{code}\n{fence}", kind="code")
    if name in {"ul", "ol"}:
        content = _render_list(tag)
        return _MarkdownBlock(content=content, kind="list") if content else None
    if name == "table":
        content = _render_table(tag)
        return _MarkdownBlock(content=content, kind="table") if content else None
    if name == "dl":
        content = _render_definition_list(tag)
        return _MarkdownBlock(content=content, kind="list") if content else None
    if name == "blockquote":
        content = _render_children(tag)
        quoted = "\n".join(f"> {line}" for line in content.splitlines())
        return _MarkdownBlock(content=quoted, kind="quote") if content else None
    content = _render_children(tag)
    return _MarkdownBlock(content=content, kind="paragraph") if content else None


def _render_children(tag: Tag, *, skip_lists: bool = False) -> str:
    parts: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in IGNORED_TAGS or (skip_lists and name in {"ul", "ol"}):
            continue
        inner = _render_children(child)
        if name == "a":
            href = str(child.get("href", "")).strip()
            parts.append(f"[{inner}]({href})" if href and inner else inner)
        elif name == "code":
            fence = "``" if "`" in inner else "`"
            parts.append(f"{fence}{inner}{fence}" if inner else "")
        elif name in {"strong", "b"}:
            parts.append(f"**{inner}**" if inner else "")
        elif name in {"em", "i"}:
            parts.append(f"*{inner}*" if inner else "")
        elif name == "br":
            parts.append("\n")
        elif name == "img":
            alt = str(child.get("alt", "")).strip()
            src = str(child.get("src", "")).strip()
            parts.append(f"![{alt}]({src})" if src else alt)
        else:
            parts.append(inner)
    return _clean_markdown_text("".join(parts))


def _render_list(tag: Tag, *, depth: int = 0) -> str:
    lines: list[str] = []
    items = tag.find_all("li", recursive=False)
    for index, item in enumerate(items, start=1):
        marker = f"{index}." if tag.name.lower() == "ol" else "-"
        text = _render_children(item, skip_lists=True)
        lines.append(f"{'  ' * depth}{marker} {text}".rstrip())
        for nested in item.find_all(["ul", "ol"], recursive=False):
            nested_text = _render_list(nested, depth=depth + 1)
            if nested_text:
                lines.append(nested_text)
    return "\n".join(lines)


def _render_table(tag: Tag) -> str:
    rows: list[list[str]] = []
    header_row = 0
    for row in tag.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if any(cell.name.lower() == "th" for cell in cells):
            header_row = len(rows)
        rows.append([_table_cell(_render_children(cell)) for cell in cells])
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    if header_row:
        normalized[0], normalized[header_row] = normalized[header_row], normalized[0]
    lines = ["| " + " | ".join(normalized[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(lines)


def _table_cell(text: str) -> str:
    return text.replace("|", r"\|").replace("\n", "<br>")


def _render_definition_list(tag: Tag) -> str:
    lines: list[str] = []
    for child in tag.find_all(["dt", "dd"], recursive=False):
        text = _render_children(child)
        if not text:
            continue
        lines.append(f"**{text}**" if child.name.lower() == "dt" else f": {text}")
    return "\n".join(lines)


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


def _clean_markdown_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()
