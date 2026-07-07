from pathlib import Path

from peoplebooks_mcp.parser.navigation import (
    iter_product_books,
    parse_book_navigation,
    parse_home_books,
    parse_products_tree,
)

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


def test_parse_products_tree_ignores_home_lists_without_products_root() -> None:
    tree = parse_products_tree(
        FIXTURES.joinpath("oracle_home.html").read_text(encoding="utf-8"),
        base_url=HOME_URL,
    )
    books = parse_home_books(
        FIXTURES.joinpath("oracle_home.html").read_text(encoding="utf-8"),
        base_url=HOME_URL,
    )

    assert tree.children == ()
    assert books["PeopleCode API Reference"].category_path == ()


def test_parse_products_tree_preserves_nested_category_paths_and_book_codes() -> None:
    tree = parse_products_tree(
        FIXTURES.joinpath("oracle_products_home.html").read_text(encoding="utf-8"),
        base_url=HOME_URL,
    )

    books = list(iter_product_books(tree))

    assert tree.title == "Products"
    assert tree.stable_id == "products"
    assert [(child.title, child.stable_id) for child in tree.children] == [
        ("Development Tools", "products/development_tools"),
        ("Administration", "products/administration"),
    ]
    assert [
        (book.book_code, book.title, tuple(category.title for category in book.category_path))
        for book in books
    ] == [
        (
            "tpcr",
            "PeopleCode API Reference",
            ("Products", "Development Tools", "PeopleCode"),
        ),
        (
            "tpcl",
            "PeopleCode Language Reference",
            ("Products", "Development Tools", "PeopleCode"),
        ),
        ("tsvt", "Server Tools", ("Products", "Administration")),
    ]
    assert books[0].stable_id == "tpcr/root"
    assert books[0].normalized is not None
    assert books[0].normalized.url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/tpcr.html"
    )


def test_parse_products_tree_handles_oracle_sidebar_span_wrapped_book_links() -> None:
    tree = parse_products_tree(
        """
        <html>
          <div id="ContentsNavBarList">
            <ul id="ul_sidebarTree">
              <li class="treeParent" id="li_prodTree1">
                <div class="treeDivTop2nd">Products</div>
                <ul class="ListBullet">
                  <li class="treeParent" aria-label="Development Tools">
                    <span class="sbparent2">Development Tools</span>
                    <ul class="ListBullet">
                      <li class="treeParent" id="lisbj_d4e38">
                        <span class="sbparent2" id="spnsbj_d4e38">
                          <a tabindex="-1" target="_top" href="tpcr.html">
                            PeopleCode API Reference
                          </a>
                        </span>
                      </li>
                    </ul>
                  </li>
                </ul>
              </li>
            </ul>
          </div>
        </html>
        """,
        base_url=HOME_URL,
    )

    books = list(iter_product_books(tree))

    assert [(book.book_code, book.title) for book in books] == [
        ("tpcr", "PeopleCode API Reference")
    ]
    assert tuple(category.title for category in books[0].category_path) == (
        "Products",
        "Development Tools",
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
