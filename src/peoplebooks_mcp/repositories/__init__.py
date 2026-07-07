"""Database repositories for PeopleBooks persistence."""

from peoplebooks_mcp.repositories.postgres import (
    BookRecord,
    ChunkInput,
    ChunkRecord,
    DocVersionRecord,
    FetchEventRecord,
    NavNodeRecord,
    PageRecord,
    PeopleBooksRepository,
    SearchResultRecord,
    SectionInput,
    SectionRecord,
    StatusCounts,
)

__all__ = [
    "BookRecord",
    "ChunkInput",
    "ChunkRecord",
    "DocVersionRecord",
    "FetchEventRecord",
    "NavNodeRecord",
    "PageRecord",
    "PeopleBooksRepository",
    "SearchResultRecord",
    "SectionInput",
    "SectionRecord",
    "StatusCounts",
]
