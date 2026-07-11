from pathlib import Path

from peoplebooks_mcp.config import load_config

CONFIG_ENV_VARS = [
    "PEOPLEBOOKS_CONFIG",
    "PEOPLEBOOKS_DATABASE_URL",
    "PEOPLEBOOKS_USER_AGENT",
    "PEOPLEBOOKS_REQUEST_TIMEOUT_SECONDS",
    "PEOPLEBOOKS_SEARCH_TIMEOUT_SECONDS",
]


def clear_config_env(monkeypatch) -> None:
    for env_var in CONFIG_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


def test_default_config_contains_peopletools_862_peoplecode_seed() -> None:
    config = load_config()

    version = config.doc_versions["pt862"]
    book = config.books["tpcr"]

    assert version.label == "PeopleTools 8.62"
    assert version.seed_url == (
        "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home"
    )
    assert book.version == "pt862"
    assert book.title == "PeopleCode API Reference"
    assert book.code == "tpcr"
    assert config.settings.search_timeout_seconds == 10.0


def test_config_uses_environment_for_local_database_url(monkeypatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv(
        "PEOPLEBOOKS_DATABASE_URL",
        "postgresql://tester:secret@localhost:5432/peoplebooks_test",
    )

    config = load_config()

    assert (
        config.settings.database_url == "postgresql://tester:secret@localhost:5432/peoplebooks_test"
    )


def test_config_file_overrides_runtime_settings(tmp_path: Path, monkeypatch) -> None:
    clear_config_env(monkeypatch)
    settings_file = tmp_path / "peoplebooks.toml"
    settings_file.write_text(
        "\n".join(
            [
                "[settings]",
                'database_url = "postgresql://local/peoplebooks"',
                'user_agent = "PeopleBooksMCP test"',
                "request_timeout_seconds = 12.5",
                "search_timeout_seconds = 7.5",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(settings_file)

    assert config.settings.database_url == "postgresql://local/peoplebooks"
    assert config.settings.user_agent == "PeopleBooksMCP test"
    assert config.settings.request_timeout_seconds == 12.5
    assert config.settings.search_timeout_seconds == 7.5


def test_load_config_discovers_local_peoplebooks_toml(tmp_path: Path, monkeypatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    Path("peoplebooks.toml").write_text(
        "\n".join(
            [
                "[settings]",
                'database_url = "postgresql://local/discovered"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.settings.database_url == "postgresql://local/discovered"
