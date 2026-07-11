from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

DEFAULT_DATABASE_URL = "postgresql://peoplebooks:peoplebooks@localhost:5432/peoplebooks"
DEFAULT_USER_AGENT = "PeopleBooksMCP/0.1.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0
DEFAULT_SEARCH_TIMEOUT_SECONDS = 10.0
DEFAULT_CONFIG_ENV = "PEOPLEBOOKS_CONFIG"
DEFAULT_TOOL_RESULT_MODE = "structured"

ToolResultMode = Literal["structured", "compatible"]


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    database_url: str = DEFAULT_DATABASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    search_timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS
    tool_result_mode: ToolResultMode = DEFAULT_TOOL_RESULT_MODE


@dataclass(frozen=True, slots=True)
class DocVersionSeed:
    code: str
    label: str
    seed_url: str


@dataclass(frozen=True, slots=True)
class BookSeed:
    code: str
    version: str
    title: str
    seed_url: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    settings: RuntimeSettings
    doc_versions: dict[str, DocVersionSeed]
    books: dict[str, BookSeed]


PT862_SEED_URL = "https://docs.oracle.com/cd/G41075_01/pt862pbr3/eng/pt/index.html?focusnode=home"

DEFAULT_DOC_VERSIONS = {
    "pt862": DocVersionSeed(
        code="pt862",
        label="PeopleTools 8.62",
        seed_url=PT862_SEED_URL,
    )
}

DEFAULT_BOOKS = {
    "tpcr": BookSeed(
        code="tpcr",
        version="pt862",
        title="PeopleCode API Reference",
        seed_url=PT862_SEED_URL,
    )
}


def load_config(path: str | Path | None = None) -> AppConfig:
    settings = RuntimeSettings()
    config_path = _resolve_config_path(path)

    if config_path is not None:
        settings = _apply_file_settings(settings, config_path)

    settings = _apply_environment_settings(settings)

    return AppConfig(
        settings=settings,
        doc_versions=dict(DEFAULT_DOC_VERSIONS),
        books=dict(DEFAULT_BOOKS),
    )


def _resolve_config_path(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path)

    env_path = os.environ.get(DEFAULT_CONFIG_ENV)
    if env_path:
        return Path(env_path)

    local_path = Path("peoplebooks.toml")
    if local_path.is_file():
        return local_path

    return None


def _apply_file_settings(settings: RuntimeSettings, path: Path) -> RuntimeSettings:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_settings = data.get("settings", {})
    if not isinstance(raw_settings, dict):
        raise ValueError("[settings] must be a table")

    return _merge_settings(settings, raw_settings)


def _apply_environment_settings(settings: RuntimeSettings) -> RuntimeSettings:
    env_settings: dict[str, Any] = {}

    if database_url := os.environ.get("PEOPLEBOOKS_DATABASE_URL"):
        env_settings["database_url"] = database_url
    if user_agent := os.environ.get("PEOPLEBOOKS_USER_AGENT"):
        env_settings["user_agent"] = user_agent
    if timeout := os.environ.get("PEOPLEBOOKS_REQUEST_TIMEOUT_SECONDS"):
        env_settings["request_timeout_seconds"] = timeout
    if timeout := os.environ.get("PEOPLEBOOKS_SEARCH_TIMEOUT_SECONDS"):
        env_settings["search_timeout_seconds"] = timeout
    if tool_result_mode := os.environ.get("PEOPLEBOOKS_TOOL_RESULT_MODE"):
        env_settings["tool_result_mode"] = tool_result_mode

    return _merge_settings(settings, env_settings)


def _merge_settings(settings: RuntimeSettings, overrides: dict[str, Any]) -> RuntimeSettings:
    accepted_keys = {
        "database_url",
        "user_agent",
        "request_timeout_seconds",
        "search_timeout_seconds",
        "tool_result_mode",
    }
    unknown_keys = sorted(set(overrides) - accepted_keys)
    if unknown_keys:
        unknown = ", ".join(unknown_keys)
        raise ValueError(f"Unknown settings keys: {unknown}")

    values = dict(overrides)
    if "request_timeout_seconds" in values:
        values["request_timeout_seconds"] = float(values["request_timeout_seconds"])
    if "search_timeout_seconds" in values:
        values["search_timeout_seconds"] = float(values["search_timeout_seconds"])
        if values["search_timeout_seconds"] <= 0:
            raise ValueError("search_timeout_seconds must be greater than zero")
    if "tool_result_mode" in values and values["tool_result_mode"] not in {
        "structured",
        "compatible",
    }:
        raise ValueError("tool_result_mode must be 'structured' or 'compatible'")

    return replace(settings, **values)
