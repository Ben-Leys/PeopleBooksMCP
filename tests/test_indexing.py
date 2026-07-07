from __future__ import annotations

from dataclasses import dataclass

import pytest

from peoplebooks_mcp.indexing import index_pages


@dataclass(frozen=True, slots=True)
class SimpleVersion:
    id: int


@dataclass(slots=True)
class FakeRepository:
    version: SimpleVersion | None
    refreshed_doc_version_id: int | None = None

    def get_doc_version_by_code(self, code: str) -> SimpleVersion | None:
        assert code == "pt862"
        return self.version

    def refresh_chunk_search_vectors(self, *, doc_version_id: int) -> int:
        self.refreshed_doc_version_id = doc_version_id
        return 3

    def mark_pages_indexed(self, *, doc_version_id: int) -> int:
        assert doc_version_id == self.refreshed_doc_version_id
        return 2


def test_index_pages_refreshes_chunk_vectors_and_marks_pages_indexed() -> None:
    repository = FakeRepository(version=SimpleVersion(id=42))

    result = index_pages(repository=repository, version_code="pt862")

    assert repository.refreshed_doc_version_id == 42
    assert result.indexed_chunks == 3
    assert result.indexed_pages == 2


def test_index_pages_rejects_unknown_version() -> None:
    repository = FakeRepository(version=None)

    with pytest.raises(ValueError, match="Unknown discovered version: 'pt862'"):
        index_pages(repository=repository, version_code="pt862")
