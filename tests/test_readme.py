from __future__ import annotations

from pathlib import Path


def test_readme_documents_local_flow_mcp_startup_and_raw_html_policy() -> None:
    readme = Path("README.md")

    text = readme.read_text(encoding="utf-8")

    assert "PeopleBooks MCP" in text
    assert "uv run alembic upgrade head" in text
    assert "uv run peoplebooks discover --version pt862 --book tpcr" in text
    assert "uv run peoplebooks scrape --version pt862 --limit 25" in text
    assert "uv run peoplebooks reparse --version pt862 --parser-version" in text
    assert "uv run peoplebooks index --version pt862" in text
    assert "uv run peoplebooks serve-mcp" in text
    assert "raw HTML" in text
    assert "not exposed through MCP" in text
    assert "search_docs" in text
    assert "get_page_outline" in text
    assert "get_section" in text
