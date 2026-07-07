from __future__ import annotations

from dataclasses import dataclass

from peoplebooks_mcp.config import AppConfig


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str


def database_config_from_app(config: AppConfig) -> DatabaseConfig:
    return DatabaseConfig(url=config.settings.database_url)
