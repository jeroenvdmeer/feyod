from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MINI_SQL = ROOT / "tests" / "fixtures" / "mini.sql"
EXPECTED_SCHEMA = ROOT / "schema" / "expected_schema.json"


@pytest.fixture
def mini_sql_path() -> Path:
    return MINI_SQL


@pytest.fixture
def expected_schema_path() -> Path:
    return EXPECTED_SCHEMA
