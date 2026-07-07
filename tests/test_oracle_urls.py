from peoplebooks_mcp.scraper.oracle import normalize_oracle_url, oracle_source_metadata


def test_normalize_oracle_url_resolves_relative_links_and_removes_fragment() -> None:
    normalized = normalize_oracle_url(
        "tpcr/langref_ArrayClass.html#top",
        base_url="https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html",
    )

    assert normalized.url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr/langref_ArrayClass.html"
    )
    assert normalized.path == "/cd/G41075_01/pt862pbr3/eng/pt/tpcr/langref_ArrayClass.html"


def test_oracle_source_metadata_keeps_peoplebooks_identifiers_and_query() -> None:
    metadata = oracle_source_metadata(
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home"
    )

    assert metadata == {
        "source": "oracle_peoplebooks",
        "host": "docs.oracle.com",
        "doc_version_path": "pt862pbr3",
        "language": "eng",
        "product": "pt",
        "query": {"focusnode": "home"},
    }
