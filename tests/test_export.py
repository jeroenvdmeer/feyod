import csv
import io
import json
import sqlite3
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from feyod_formats import build, export


@pytest.fixture
def conn(mini_sql_path, tmp_path):
    c = build.load_dump(mini_sql_path, tmp_path / "mini.db")
    yield c
    c.close()


@pytest.fixture
def expected(expected_schema_path):
    return json.loads(expected_schema_path.read_text(encoding="utf-8"))


def test_parquet_scores_are_int64_with_nulls(conn, expected, tmp_path):
    export.export_parquet(conn, tmp_path, expected)
    t = pq.read_table(tmp_path / "matches.parquet")
    for col in ("homeClubFinalScore", "awayClubFinalScore", "homeClubPenalties"):
        assert t.schema.field(col).type == pa.int64()
    assert t.schema.field("dateAndTime").type == pa.string()
    scores = t.column("homeClubFinalScore").to_pylist()
    assert 3 in scores and None in scores
    assert t.column_names == expected["matches"]


def test_parquet_row_counts_and_files(conn, expected, tmp_path):
    export.export_parquet(conn, tmp_path, expected)
    assert sorted(p.name for p in tmp_path.glob("*.parquet")) == sorted(
        f"{t}.parquet" for t in expected
    )
    for t in expected:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        assert pq.read_table(tmp_path / f"{t}.parquet").num_rows == n


def test_parquet_keeps_diacritics_and_apostrophe(conn, expected, tmp_path):
    export.export_parquet(conn, tmp_path, expected)
    names = pq.read_table(tmp_path / "players.parquet").column("playerName").to_pylist()
    assert "Ståle Solbakken" in names
    home = pq.read_table(tmp_path / "matches.parquet").column("homeClubName").to_pylist()
    assert "NAC '12" in home


def _zip(conn, expected, tmp_path):
    z = tmp_path / "feyod-csv.zip"
    lic = tmp_path / "LICENSE"
    lic.write_text("CC0 text\n", encoding="utf-8")
    export.export_csv_zip(conn, z, expected, lic)
    return zipfile.ZipFile(z)


def test_zip_contents(conn, expected, tmp_path):
    with _zip(conn, expected, tmp_path) as zf:
        assert sorted(zf.namelist()) == sorted(
            [f"{t}.csv" for t in expected] + ["LICENSE", "README.txt"]
        )
        assert len(expected) == 9
        readme = zf.read("README.txt").decode("utf-8")
        assert "UTF-8" in readme and "Excel" in readme


def test_csv_rows_header_nulls_and_encoding(conn, expected, tmp_path):
    with _zip(conn, expected, tmp_path) as zf:
        for t, cols in expected.items():
            raw = zf.read(f"{t}.csv")
            assert not raw.startswith(b"\xef\xbb\xbf")
            assert b"\r" not in raw
            rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
            assert rows[0] == cols
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            assert len(rows) - 1 == n
        rows = list(
            csv.DictReader(io.StringIO(zf.read("matches.csv").decode("utf-8")))
        )
        assert rows[0]["homeClubFinalScore"] == "3"
        assert rows[1]["homeClubFinalScore"] == ""
        assert rows[1]["homeClubName"] == "NAC '12"
        players = zf.read("players.csv").decode("utf-8")
        assert "Ståle Solbakken" in players


def test_csv_quotes_commas(tmp_path):
    c = sqlite3.connect(":memory:")
    c.execute('CREATE TABLE t ("a" INTEGER, "b" TEXT)')
    c.execute("INSERT INTO t VALUES (1, 'x, \"y\"')")
    lic = tmp_path / "LICENSE"
    lic.write_text("x", encoding="utf-8")
    export.export_csv_zip(c, tmp_path / "z.zip", {"t": ["a", "b"]}, lic)
    with zipfile.ZipFile(tmp_path / "z.zip") as zf:
        raw = zf.read("t.csv").decode("utf-8")
    assert '"x, ""y"""' in raw
    assert list(csv.reader(io.StringIO(raw)))[1] == ["1", 'x, "y"']


def test_unknown_sqlite_type_fails(tmp_path):
    c = sqlite3.connect(":memory:")
    c.execute('CREATE TABLE t ("a" REAL)')
    with pytest.raises(build.BuildError, match="REAL"):
        export.export_parquet(c, tmp_path, {"t": ["a"]})


def test_column_mismatch_fails(conn, tmp_path):
    with pytest.raises(build.BuildError, match="clubs"):
        export.export_parquet(conn, tmp_path, {"clubs": ["clubId", "nope"]})


def test_zip_readme_names_stale_with_diacritic(conn, expected, tmp_path):
    with _zip(conn, expected, tmp_path) as zf:
        assert "Ståle" in zf.read("README.txt").decode("utf-8")
