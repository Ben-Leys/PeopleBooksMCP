from peoplebooks_mcp.database import run_migrations
from peoplebooks_mcp.repositories import PeopleBooksRepository


def test_repository_status_counts_pages_by_lifecycle_state(postgres_url: str) -> None:
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
            seed_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html",
        )
        repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/a.html",
            normalized_path="/a.html",
            source_url="https://docs.oracle.com/a.html",
            title="Queued",
        )
        fetched = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/b.html",
            normalized_path="/b.html",
            source_url="https://docs.oracle.com/b.html",
            title="Fetched",
        )
        failed = repository.queue_page(
            doc_version_id=version.id,
            book_id=book.id,
            normalized_url="https://docs.oracle.com/c.html",
            normalized_path="/c.html",
            source_url="https://docs.oracle.com/c.html",
            title="Failed",
        )

        repository.record_fetch_success(
            page_id=fetched.id,
            raw_html="<html></html>",
            content_hash="sha256:ok",
            status_code=200,
            elapsed_ms=10,
            source_url=fetched.source_url,
        )
        repository.record_fetch_failure(
            page_id=failed.id,
            error_message="HTTP 500",
            status_code=500,
            elapsed_ms=12,
            source_url=failed.source_url,
        )

        counts = repository.get_status_counts(doc_version_id=version.id)

    assert counts.discovered == 3
    assert counts.queued == 1
    assert counts.fetched == 1
    assert counts.failed == 1
    assert counts.parsed == 0
    assert counts.indexed == 0
