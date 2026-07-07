import pytest

from tests.postgres_test_utils import TEST_DATABASE_ENV, require_postgres_url


def test_require_postgres_url_loads_test_database_url_from_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(TEST_DATABASE_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath(".env").write_text(
        f'{TEST_DATABASE_ENV}="postgresql://tester:secret@localhost:5432/peoplebooks_test"\n',
        encoding="utf-8",
    )

    try:
        database_url = require_postgres_url()
    except pytest.skip.Exception as error:
        pytest.fail(f"Expected {TEST_DATABASE_ENV} to load from .env, got skip: {error}")

    assert database_url == "postgresql://tester:secret@localhost:5432/peoplebooks_test"
