from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DATABASE_ENV = "PEOPLEBOOKS_TEST_DATABASE_URL"


def require_postgres_url() -> str:
    database_url = os.environ.get(TEST_DATABASE_ENV) or _read_dotenv_value(TEST_DATABASE_ENV)
    if not database_url:
        pytest.skip(f"{TEST_DATABASE_ENV} is not set")

    database_name = urlparse(database_url).path.lstrip("/")
    if "test" not in database_name.lower():
        pytest.fail(
            f"{TEST_DATABASE_ENV} must point to a disposable test database; "
            f"database name {database_name!r} does not contain 'test'"
        )

    return database_url


def _read_dotenv_value(key: str, path: str | Path = ".env") -> str | None:
    dotenv_path = Path(path)
    if not dotenv_path.is_file():
        return None

    prefix = f"{key}="
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue

        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value

    return None


@pytest.fixture
def postgres_url() -> str:
    database_url = require_postgres_url()
    reset_public_schema(database_url)
    return database_url


def reset_public_schema(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")


def table_names(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            """
        ).fetchall()
    return {row[0] for row in rows}


def column_names(database_url: str, table_name: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            """,
            (table_name,),
        ).fetchall()
    return {row[0] for row in rows}


def index_names(database_url: str, table_name: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
            """,
            (table_name,),
        ).fetchall()
    return {row[0] for row in rows}


def constraint_names(database_url: str, table_name: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = %s::regclass
            """,
            (table_name,),
        ).fetchall()
    return {row[0] for row in rows}
