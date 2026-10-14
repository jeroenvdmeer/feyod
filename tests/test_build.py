import json
import sqlite3

import pytest

from feyod_formats import build
from feyod_formats.build import BuildError



@pytest.fixture
def expected(expected_schema_path):
    return json.loads(expected_schema_path.read_text(encoding="utf-8"))


def load(tmp_path, sql_text, name="t.db"):
    sql = tmp_path / "in.sql"
    sql.write_text(sql_text, encoding="utf-8")
    return build.load_dump(sql, tmp_path / name)


@pytest.fixture
def mini_text(mini_sql_path):
    return mini_sql_path.read_text(encoding="utf-8")


@pytest.fixture
def mini_conn(tmp_path, mini_sql_path):
    conn = build.load_dump(mini_sql_path, tmp_path / "mini.db")
    yield conn
    conn.close()


def test_happy_path(mini_conn, expected, tmp_path):
    build.check_integrity(mini_conn)
    build.check_schema(mini_conn, expected)
    build.check_nonempty(mini_conn)
    counts = build.row_counts(mini_conn)
    assert set(counts) == set(expected)
    for table, n in counts.items():
        assert n == mini_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        assert n >= 1
    out = tmp_path / "manifest.json"
    build.write_manifest(out, counts, "abc123", "2026-10-14")
    m = json.loads(out.read_text(encoding="utf-8"))
    assert m["source_sha"] == "abc123"
    assert m["build_date"] == "2026-10-14"
    assert m["row_counts"] == counts


def test_load_dump_writes_db_file(tmp_path, mini_sql_path):
    db = tmp_path / "out.db"
    conn = build.load_dump(mini_sql_path, db)
    conn.close()
    assert db.exists() and db.stat().st_size > 0


def test_extra_table_fails(tmp_path, mini_text, expected):
    text = mini_text.replace(
        "COMMIT;", 'CREATE TABLE "match_sources" ("matchId" INTEGER, "url" TEXT);\nCOMMIT;'
    )
    assert text != mini_text
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "match_sources" in str(e.value)


def test_extra_column_fails(tmp_path, mini_text, expected):
    text = mini_text.replace(
        'CREATE TABLE "matches" (', 'CREATE TABLE "matches" ("delpherSourceUrl" TEXT, ', 1
    )
    assert text != mini_text
    # inserts use explicit column lists, so the dump still loads
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    msg = str(e.value)
    assert "delpherSourceUrl" in msg and "matches" in msg


def test_missing_column_fails(tmp_path, mini_text, expected):
    exp = {t: list(c) for t, c in expected.items()}
    exp["clubs"].append("phantomColumn")
    conn = load(tmp_path, mini_text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, exp)
    assert "phantomColumn" in str(e.value)


def test_column_order_matters(tmp_path, mini_text, expected):
    exp = {t: list(c) for t, c in expected.items()}
    exp["clubs"].reverse()
    conn = load(tmp_path, mini_text)
    with pytest.raises(BuildError):
        build.check_schema(conn, exp)


def test_missing_table_fails(tmp_path, mini_text, expected):
    exp = dict(expected)
    del exp["cards"]  # dump now has a table the allowlist lacks -> extra
    conn = load(tmp_path, mini_text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, exp)
    assert "cards" in str(e.value)

    # and the real missing-table case: expected table absent from the db
    conn2 = load(tmp_path, mini_text, "t2.db")
    conn2.execute("PRAGMA foreign_keys = OFF")
    conn2.execute('DROP TABLE "cards"')
    with pytest.raises(BuildError) as e2:
        build.check_schema(conn2, expected)
    assert "cards" in str(e2.value)


def test_empty_table_fails(tmp_path, mini_text):
    conn = load(tmp_path, mini_text)
    conn.execute('DELETE FROM "cards"')
    with pytest.raises(BuildError) as e:
        build.check_nonempty(conn)
    assert "cards" in str(e.value)


def test_fk_violation_fails(tmp_path, mini_text):
    conn = load(tmp_path, mini_text)
    conn.execute(
        'INSERT INTO "lineups" ("matchId","playerId","clubId","starting") '
        "SELECT \"matchId\", 99999, \"homeClubId\", 1 FROM matches LIMIT 1"
    )
    conn.commit()
    with pytest.raises(BuildError) as e:
        build.check_integrity(conn)
    assert "lineups" in str(e.value)


def test_integrity_check_failure_message(tmp_path):
    # a connection that is not a valid sqlite db content-wise: simulate via stub
    class Stub:
        def execute(self, sql, *a):
            class C:
                def fetchone(s):
                    return ("*** in database main ***",)

                def fetchall(s):
                    return []

            return C()

    with pytest.raises(BuildError):
        build.check_integrity(Stub())


def test_real_dump(tmp_path, expected):
    from pathlib import Path

    sql = Path(__file__).resolve().parent.parent / "feyod.sql"
    conn = build.load_dump(sql, tmp_path / "real.db")
    try:
        build.check_integrity(conn)
        build.check_schema(conn, expected)
        build.check_nonempty(conn)
        counts = build.row_counts(conn)
        assert set(counts) == set(expected)
        assert all(n > 0 for n in counts.values())
    finally:
        conn.close()
