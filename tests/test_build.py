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


def test_table_missing_from_allowlist_fails(tmp_path, mini_text, expected):
    exp = dict(expected)
    del exp["cards"]  # dump has a table the allowlist lacks -> extra
    conn = load(tmp_path, mini_text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, exp)
    assert "extra tables" in str(e.value) and "cards" in str(e.value)


def test_missing_table_fails(tmp_path, mini_text, expected):
    conn = load(tmp_path, mini_text)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute('DROP TABLE "cards"')
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "missing tables" in str(e.value) and "cards" in str(e.value)


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


# ---- fix round 1: bypasses found in review ----


def inject(text, extra):
    out = text.replace("COMMIT;", extra + "\nCOMMIT;")
    assert out != text
    return out


def test_like_wildcard_table_name_fails(tmp_path, mini_text, expected):
    text = inject(
        mini_text,
        'CREATE TABLE "sqlite0match_sources" (url TEXT);'
        "INSERT INTO \"sqlite0match_sources\" VALUES ('http://leak');",
    )
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "sqlite0match_sources" in str(e.value)


def test_sqlite_stat_rows_fail(tmp_path, mini_text, expected):
    conn = load(tmp_path, mini_text)
    conn.execute("ANALYZE")
    conn.execute("DELETE FROM sqlite_stat1")
    build.check_schema(conn, expected)  # empty stat table is fine
    conn.execute("INSERT INTO sqlite_stat1 VALUES ('matches', NULL, 'http://leak')")
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "sqlite_stat1" in str(e.value)


def test_view_named_like_private_table_fails(tmp_path, mini_text, expected):
    text = inject(mini_text, "CREATE VIEW match_sources AS SELECT matchId FROM matches;")
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "match_sources" in str(e.value)


def test_view_adding_column_fails(tmp_path, mini_text, expected):
    text = inject(
        mini_text,
        "CREATE VIEW matches_plus AS SELECT *, 'u' AS delpherSourceUrl FROM matches;",
    )
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "matches_plus" in str(e.value)


def test_trigger_fails(tmp_path, mini_text, expected):
    text = inject(
        mini_text,
        "CREATE TRIGGER trg AFTER INSERT ON clubs BEGIN SELECT 1; END;",
    )
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "trg" in str(e.value)


def test_explicit_index_fails(tmp_path, mini_text, expected):
    text = inject(mini_text, 'CREATE INDEX idx_x ON clubs("clubName");')
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "idx_x" in str(e.value)


def test_generated_column_fails(tmp_path, mini_text, expected):
    text = mini_text.replace(
        'CREATE TABLE "matches" (',
        "CREATE TABLE \"matches\" (\"delpherSourceUrl\" TEXT GENERATED ALWAYS AS ('u') VIRTUAL, ",
        1,
    )
    assert text != mini_text
    conn = load(tmp_path, text)
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "delpherSourceUrl" in str(e.value)


def test_dump_without_commit_fails(tmp_path, mini_text):
    text = mini_text.replace("COMMIT;", "")
    assert text != mini_text
    with pytest.raises(BuildError) as e:
        load(tmp_path, text)
    assert "transaction" in str(e.value)


def test_temp_table_fails(tmp_path, mini_text, expected):
    conn = load(tmp_path, mini_text)
    conn.execute("CREATE TEMP TABLE match_media (url TEXT)")
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "temp" in str(e.value).lower()


def test_attached_database_fails(tmp_path, mini_text, expected):
    conn = load(tmp_path, mini_text)
    conn.execute("ATTACH DATABASE ':memory:' AS other")
    with pytest.raises(BuildError) as e:
        build.check_schema(conn, expected)
    assert "other" in str(e.value)


def test_run_gate_happy_and_failing(tmp_path, mini_text, expected):
    conn = load(tmp_path, mini_text)
    counts = build.run_gate(conn, expected)
    assert counts == build.row_counts(conn)
    conn.execute('DELETE FROM "cards"')
    with pytest.raises(BuildError):
        build.run_gate(conn, expected)


def test_dropped_table_leaves_no_bytes_in_published_db(tmp_path, mini_text):
    from feyod_formats.__main__ import main

    marker = "SECRET-MARKER-delpher-" + "x" * 40
    sql = tmp_path / "leaky.sql"
    sql.write_text(
        mini_text
        + '\nCREATE TABLE "match_media" ("id" INTEGER, "url" TEXT);\n'
        + "".join(
            f"INSERT INTO \"match_media\" VALUES ({i},'{marker}{i}');\n"
            for i in range(50)
        )
        + 'DROP TABLE "match_media";\n',
        encoding="utf-8",
    )
    assert main(["build", "--sql", str(sql), "--out", str(tmp_path / "out")]) == 0
    data = (tmp_path / "out" / "hf" / "feyod.db").read_bytes()
    assert marker.encode() not in data
