import json
import sqlite3

TABLES = [
    "cards", "clubs", "competitions", "goals", "lineups",
    "matches", "players", "seasons", "substitutions",
]


def load_mini(path):
    con = sqlite3.connect(":memory:")
    con.executescript(path.read_text(encoding="utf-8"))
    return con


def test_mini_sql_matches_expected_schema(mini_sql_path, expected_schema_path):
    expected = json.loads(expected_schema_path.read_text(encoding="utf-8"))
    con = load_mini(mini_sql_path)
    actual_tables = sorted(
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    assert actual_tables == sorted(expected) == TABLES
    for table, cols in expected.items():
        actual = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
        assert actual == cols, table
        assert con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] >= 1, table


def test_mini_sql_integrity(mini_sql_path):
    con = load_mini(mini_sql_path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_mini_sql_edge_cases(mini_sql_path):
    con = load_mini(mini_sql_path)
    assert con.execute(
        'SELECT COUNT(*) FROM matches WHERE "homeClubFinalScore" IS NULL '
        'AND "awayClubFinalScore" IS NULL AND "homeClubPenalties" IS NULL '
        'AND "awayClubPenalties" IS NULL'
    ).fetchone()[0] >= 1
    players = {r[0] for r in con.execute('SELECT "playerName" FROM players')}
    assert {"Ruud Gullit", "Ståle Solbakken"} <= players
    clubs = {r[0] for r in con.execute('SELECT "clubName" FROM clubs')}
    assert {"Go Ahead Eagles", "NAC '12"} <= clubs
    assert any("," in c for c in clubs | players)
