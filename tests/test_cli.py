from typer.testing import CliRunner

from peoplebooks_mcp.cli import app


def test_cli_help_lists_planned_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["discover", "scrape", "status", "reparse", "index", "serve-mcp"]:
        assert command in result.output


def test_discover_help_shows_seed_options() -> None:
    result = CliRunner().invoke(app, ["discover", "--help"])

    assert result.exit_code == 0
    assert "--version" in result.output
    assert "--book" in result.output
