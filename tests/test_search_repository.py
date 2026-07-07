from __future__ import annotations

from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.indexing import index_pages
from peoplebooks_mcp.repositories import ChunkInput, PeopleBooksRepository, SectionInput


def test_repository_search_returns_ranked_snippets_and_stable_ids(postgres_url: str) -> None:
    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        book = repository.upsert_book(
            doc_version_id=version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        create_array_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/createarray.html",
            title="CreateArray",
        )
        delete_row_page = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/deleterow.html",
            normalized_path="/cd/G41075_01/pt862pbr3/eng/pt/tpcr/deleterow.html",
            source_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/deleterow.html",
            title="DeleteRow",
        )
        repository.replace_page_sections(
            page_id=create_array_page.id,
            parser_version="parser-v1",
            sections=[
                SectionInput(
                    stable_id="createarray",
                    heading="CreateArray",
                    level=1,
                    section_path=("CreateArray",),
                    ordinal=0,
                    content="CreateArray returns an array object for PeopleCode programs.",
                    chunks=[
                        ChunkInput(
                            stable_id="createarray-0",
                            ordinal=0,
                            content="CreateArray returns an array object for PeopleCode programs.",
                            metadata={"kind": "summary"},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )
        repository.replace_page_sections(
            page_id=delete_row_page.id,
            parser_version="parser-v1",
            sections=[
                SectionInput(
                    stable_id="deleterow",
                    heading="DeleteRow",
                    level=1,
                    section_path=("DeleteRow",),
                    ordinal=0,
                    content="DeleteRow removes a row from a component buffer.",
                    chunks=[
                        ChunkInput(
                            stable_id="deleterow-0",
                            ordinal=0,
                            content=(
                                "DeleteRow removes rows. "
                                "It mentions array only as unrelated text."
                            ),
                            metadata={"kind": "summary"},
                        )
                    ],
                    source_metadata={},
                )
            ],
        )

        index_result = index_pages(repository=repository, version_code="pt862")
        results = repository.search_chunks(
            doc_version_id=version.id,
            query="array object",
            limit=5,
        )
        counts = repository.get_status_counts(doc_version_id=version.id)

    assert index_result.indexed_chunks == 2
    assert index_result.indexed_pages == 2
    assert counts.indexed == 2
    assert [result.chunk_stable_id for result in results] == ["createarray-0"]
    assert results[0].version_code == "pt862"
    assert results[0].book_code == "tpcr"
    assert results[0].page_title == "CreateArray"
    assert results[0].section_path == ["CreateArray"]
    assert results[0].source_url.endswith("/createarray.html")
    assert results[0].section_stable_id == "createarray"
    assert "<mark>array</mark>" in results[0].snippet.lower()


def test_repository_search_is_scoped_to_doc_version(postgres_url: str) -> None:
    run_migrations(postgres_url)

    with PeopleBooksRepository.connect(postgres_url) as repository:
        first_version = repository.upsert_doc_version(
            code="pt862",
            label="PeopleTools 8.62",
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html",
        )
        second_version = repository.upsert_doc_version(
            code="pt861",
            label="PeopleTools 8.61",
            seed_url="https://docs.oracle.com/cd/example/pt861/index.html",
        )
        first_book = repository.upsert_book(
            doc_version_id=first_version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=first_version.seed_url,
        )
        second_book = repository.upsert_book(
            doc_version_id=second_version.id,
            code="tpcr",
            title="PeopleCode API Reference",
            seed_url=second_version.seed_url,
        )
        first_page = _queue_indexed_page(
            repository=repository,
            doc_version_id=first_version.id,
            book_id=first_book.id,
            slug="first",
            content="SearchUniqueTerm belongs to the first version.",
        )
        _queue_indexed_page(
            repository=repository,
            doc_version_id=second_version.id,
            book_id=second_book.id,
            slug="second",
            content="SearchUniqueTerm belongs to the second version.",
        )

        index_pages(repository=repository, version_code="pt862")
        index_pages(repository=repository, version_code="pt861")
        results = repository.search_chunks(
            doc_version_id=first_version.id,
            query="SearchUniqueTerm",
            limit=5,
        )

    assert [result.page_id for result in results] == [first_page.id]
    assert [result.version_code for result in results] == ["pt862"]


def _queue_indexed_page(
    *,
    repository: PeopleBooksRepository,
    doc_version_id: int,
    book_id: int,
    slug: str,
    content: str,
):
    page = repository.queue_page(
        doc_version_id=doc_version_id,
        book_id=book_id,
        normalized_url=f"https://docs.oracle.com/{slug}.html",
        normalized_path=f"/{slug}.html",
        source_url=f"https://docs.oracle.com/{slug}.html",
        title=slug.title(),
    )
    repository.replace_page_sections(
        page_id=page.id,
        parser_version="parser-v1",
        sections=[
            SectionInput(
                stable_id=slug,
                heading=slug.title(),
                level=1,
                section_path=(slug.title(),),
                ordinal=0,
                content=content,
                chunks=[
                    ChunkInput(
                        stable_id=f"{slug}-0",
                        ordinal=0,
                        content=content,
                        metadata={},
                    )
                ],
                source_metadata={},
            )
        ],
    )
    return page
