"""Database repositories for PeopleBooks persistence."""

from peoplebooks_mcp.repositories.postgres import (
    EXPECTED_SCHEMA_REVISION,
    BookRecord,
    ChunkInput,
    ChunkRecord,
    ContentHealthRecord,
    DocVersionRecord,
    FetchEventRecord,
    NavNodeRecord,
    PageRecord,
    PageSearchRecord,
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
    "ContentHealthRecord",
    "DocVersionRecord",
    "EXPECTED_SCHEMA_REVISION",
    "FetchEventRecord",
    "NavNodeRecord",
    "PageRecord",
    "PageSearchRecord",
    "PeopleBooksRepository",
    "SearchResultRecord",
    "SectionInput",
    "SectionRecord",
    "StatusCounts",
]
