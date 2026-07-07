from pathlib import Path

from peoplebooks_mcp.parser.navigation import parse_book_navigation, parse_home_books

FIXTURES = Path(__file__).parent / "fixtures"
HOME_URL = "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html"
BOOK_URL = "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html"


def test_parse_home_books_finds_configured_book_link() -> None:
    books = parse_home_books(
        FIXTURES.joinpath("oracle_home.html").read_text(encoding="utf-8"),
        base_url=HOME_URL,
    )

    assert books["PeopleCode API Reference"].source_url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html?focusnode=tpcr"
    )
    assert books["PeopleCode API Reference"].normalized.url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html"
    )


def test_parse_book_navigation_extracts_book_page_links_only() -> None:
    nodes = parse_book_navigation(
        FIXTURES.joinpath("oracle_tpcr_book.html").read_text(encoding="utf-8"),
        base_url=BOOK_URL,
        book_code="tpcr",
    )

    assert [(node.title, node.normalized.path) for node in nodes] == [
        (
            "Application Class",
            "/cd/G41075_01/pt862pbr3/eng/pt/tpcr/langref_ApplicationClass.html",
        ),
        (
            "Array Class",
            "/cd/G41075_01/pt862pbr3/eng/pt/tpcr/langref_ArrayClass.html",
        ),
    ]
    assert [node.stable_id for node in nodes] == [
        "tpcr/langref_applicationclass",
        "tpcr/langref_arrayclass",
    ]
    assert nodes[0].source_url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/"
        "tpcr/langref_ApplicationClass.html?focusnode=abc"
    )
