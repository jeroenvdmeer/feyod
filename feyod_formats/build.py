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


def _actual_schema(conn) -> dict:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        t: [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')] for t in tables
    }


def check_schema(conn, expected) -> None:
    """Allowlist gate (D1): tables and ordered columns must match exactly."""
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
