"""Build core: load the public dump, run the publication gate, write the manifest.

Every check raises BuildError so callers (the CLI) can exit non-zero.
"""

import json
import sqlite3
from pathlib import Path


class BuildError(Exception):
    """A publication-gate check failed; nothing may be published."""


def load_dump(sql_path, db_path) -> sqlite3.Connection:
    """Load the SQL dump into a fresh on-disk SQLite database."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    sql = Path(sql_path).read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql)
    except sqlite3.Error as exc:
        conn.close()
        raise BuildError(f"loading {sql_path} failed: {exc}") from exc
    if conn.in_transaction:
        conn.close()
        raise BuildError(
            f"{sql_path} left a transaction open (missing COMMIT?); "
            "the db file on disk would be empty"
        )
    return conn


def check_integrity(conn) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise BuildError(f"integrity_check failed: {result}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        tables = sorted({v[0] for v in violations})
        raise BuildError(
            f"foreign_key_check found {len(violations)} violation(s) in "
            f"table(s) {tables}; first: {violations[0]}"
        )


# SQLite-internal tables that may exist; everything else must be in the allowlist.
# Exact names only (a LIKE 'sqlite_%' filter would also match e.g. 'sqlite0x').
INTERNAL_TABLES = frozenset(
    {"sqlite_sequence", "sqlite_stat1", "sqlite_stat2", "sqlite_stat3", "sqlite_stat4"}
)
AUTOINDEX_PREFIX = "sqlite_autoindex_"


def _actual_schema(conn) -> dict:
    tables = [
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if r[0] not in INTERNAL_TABLES
    ]
    # table_xinfo (not table_info) also lists generated/hidden columns
    return {
        t: [r[1] for r in conn.execute(f'PRAGMA table_xinfo("{t}")')] for t in tables
    }


def _check_no_hidden_objects(conn) -> None:
    problems = []
    for typ, name in conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type != 'table'"
    ):
        if typ == "index" and name.startswith(AUTOINDEX_PREFIX):
            continue
        problems.append(f"{typ} {name!r}")
    if problems:
        raise BuildError(
            "unexpected schema objects (only tables and autoindexes allowed): "
            + ", ".join(problems)
        )
    for t in sorted(INTERNAL_TABLES - {"sqlite_sequence"}):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()
        if exists and conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]:
            raise BuildError(f"internal table {t!r} contains rows")
    temp = conn.execute("SELECT type, name FROM sqlite_temp_master").fetchall()
    if temp:
        raise BuildError(f"temp schema objects present: {temp}")
    # 'temp' is listed once touched; its contents were checked above
    dbs = [r[1] for r in conn.execute("PRAGMA database_list") if r[1] != "temp"]
    if dbs != ["main"]:
        raise BuildError(f"unexpected databases attached: {dbs}")


def check_schema(conn, expected) -> None:
    """Allowlist gate (D1): tables and ordered columns must match exactly."""
    _check_no_hidden_objects(conn)
    actual = _actual_schema(conn)
    problems = []
    extra_tables = sorted(set(actual) - set(expected))
    missing_tables = sorted(set(expected) - set(actual))
    if extra_tables:
        problems.append(f"extra tables not in allowlist: {extra_tables}")
    if missing_tables:
        problems.append(f"missing tables: {missing_tables}")
    for table in sorted(set(actual) & set(expected)):
        have, want = actual[table], list(expected[table])
        if have == want:
            continue
        extra = [c for c in have if c not in want]
        missing = [c for c in want if c not in have]
        detail = f"table {table!r}: "
        if extra:
            detail += f"extra columns {extra}; "
        if missing:
            detail += f"missing columns {missing}; "
        if not extra and not missing:
            detail += f"column order differs (have {have}, expected {want}); "
        problems.append(detail.rstrip("; "))
    if problems:
        raise BuildError("schema does not match allowlist: " + " | ".join(problems))


def row_counts(conn) -> dict:
    return {
        t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for t in sorted(_actual_schema(conn))
    }


def check_nonempty(conn) -> None:
    empty = [t for t, n in row_counts(conn).items() if n == 0]
    if empty:
        raise BuildError(f"empty tables: {empty}")


def write_manifest(path, counts, source_sha, build_date) -> None:
    manifest = {
        "source_sha": source_sha,
        "build_date": build_date,
        "row_counts": dict(counts),
        "total_rows": sum(counts.values()),
    }
    Path(path).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_gate(conn, expected) -> dict:
    """Run all checks in the required order; return the row counts."""
    check_integrity(conn)
    check_schema(conn, expected)
    check_nonempty(conn)
    return row_counts(conn)
