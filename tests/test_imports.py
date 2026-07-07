from importlib import import_module


def test_foundation_modules_import() -> None:
    assert import_module("peoplebooks_mcp").__version__ == "0.1.0"

    for module_name in [
        "peoplebooks_mcp.cli",
        "peoplebooks_mcp.config",
        "peoplebooks_mcp.database",
        "peoplebooks_mcp.indexing",
        "peoplebooks_mcp.mcp_server",
        "peoplebooks_mcp.parser",
        "peoplebooks_mcp.repositories",
        "peoplebooks_mcp.scraper",
    ]:
        assert import_module(module_name)
