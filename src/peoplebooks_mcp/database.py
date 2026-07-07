from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row

from peoplebooks_mcp.config import AppConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str


def database_config_from_app(config: AppConfig) -> DatabaseConfig:
    return DatabaseConfig(url=config.settings.database_url)


def run_migrations(database_url: str, revision: str = "head") -> None:
    """Apply Alembic migrations to the configured PostgreSQL database."""
    command.upgrade(_alembic_config(database_url), revision)


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
        yield connection


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", _sqlalchemy_database_url(database_url))
    return config


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url
