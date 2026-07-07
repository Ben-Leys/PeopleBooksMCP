from pathlib import Path

from peoplebooks_mcp.parser.leaf import parse_leaf_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_leaf_page_extracts_h1_h2_h3_sections_with_paths_and_chunks() -> None:
    sections = parse_leaf_page(
        FIXTURES.joinpath("oracle_tpcr_leaf.html").read_text(encoding="utf-8"),
        page_stable_id="tpcr/langref_applicationclass",
    )

    assert [(section.heading, section.level, section.section_path) for section in sections] == [
        ("Application Class", 1, ("Application Class",)),
        ("Constructors", 2, ("Application Class", "Constructors")),
        ("Parameters", 3, ("Application Class", "Constructors", "Parameters")),
        ("Methods", 2, ("Application Class", "Methods")),
    ]
    assert sections[0].stable_id == "tpcr/langref_applicationclass/application-class"
    assert sections[2].content == "name is the application name."
    assert sections[2].chunks[0].stable_id == (
        "tpcr/langref_applicationclass/application-class-constructors-parameters/chunk-0"
    )
    assert sections[2].chunks[0].metadata == {
        "section_heading": "Parameters",
        "section_path": ["Application Class", "Constructors", "Parameters"],
    }


def test_parse_leaf_page_falls_back_to_title_when_no_h1_is_present() -> None:
    html = """
    <html>
      <head><title>CreateArray</title></head>
      <body><p>CreateArray returns an array object.</p></body>
    </html>
    """

    sections = parse_leaf_page(html, page_stable_id="tpcr/langref_createarray")

    assert len(sections) == 1
    assert sections[0].heading == "CreateArray"
    assert sections[0].level == 1
    assert sections[0].content == "CreateArray returns an array object."
    assert sections[0].stable_id == "tpcr/langref_createarray/createarray"


def test_parse_leaf_page_stable_ids_include_parent_headings_for_repeated_names() -> None:
    html = """
    <html>
      <body>
        <h1>Application Class</h1>
        <h2>Constructors</h2>
        <h3>Parameters</h3>
        <p>Constructor parameters.</p>
        <h2>Methods</h2>
        <h3>Parameters</h3>
        <p>Method parameters.</p>
      </body>
    </html>
    """

    sections = parse_leaf_page(html, page_stable_id="tpcr/langref_applicationclass")

    assert [section.stable_id for section in sections] == [
        "tpcr/langref_applicationclass/application-class",
        "tpcr/langref_applicationclass/application-class-constructors",
        "tpcr/langref_applicationclass/application-class-constructors-parameters",
        "tpcr/langref_applicationclass/application-class-methods",
        "tpcr/langref_applicationclass/application-class-methods-parameters",
    ]


def test_parse_leaf_page_preserves_preformatted_code_lines() -> None:
    html = """
    <html>
      <body>
        <h1>Example</h1>
        <pre>
Local ApiObject &app;
&app = %Session.GetCompIntfc(CompIntfc.MY_APP);
If &app.Save() Then
   MessageBox(0, "", 0, 0, "Saved");
End-If;
        </pre>
      </body>
    </html>
    """

    sections = parse_leaf_page(html, page_stable_id="tpcr/langref_example")

    assert sections[0].content == (
        "Local ApiObject &app;\n"
        "&app = %Session.GetCompIntfc(CompIntfc.MY_APP);\n"
        "If &app.Save() Then\n"
        '   MessageBox(0, "", 0, 0, "Saved");\n'
        "End-If;"
    )
