"""Full-text indexing entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DocVersionLike(Protocol):
    id: int


class IndexRepository(Protocol):
    def get_doc_version_by_code(self, code: str) -> DocVersionLike | None:
        pass

    def refresh_chunk_search_vectors(self, *, doc_version_id: int) -> int:
        pass

    def mark_pages_indexed(self, *, doc_version_id: int) -> int:
        pass


@dataclass(frozen=True, slots=True)
class IndexResult:
    indexed_chunks: int
    indexed_pages: int


def index_pages(*, repository: IndexRepository, version_code: str) -> IndexResult:
    doc_version = repository.get_doc_version_by_code(version_code)
    if doc_version is None:
        raise ValueError(f"Unknown discovered version: {version_code!r}")

    indexed_chunks = repository.refresh_chunk_search_vectors(doc_version_id=doc_version.id)
    indexed_pages = repository.mark_pages_indexed(doc_version_id=doc_version.id)
    return IndexResult(indexed_chunks=indexed_chunks, indexed_pages=indexed_pages)
