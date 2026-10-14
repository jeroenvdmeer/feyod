"""Exporters: typed Parquet per table and a CSV zip.

Column order follows the schema allowlist; types follow the declared SQLite
types (D2). Any mismatch or unknown type raises BuildError.
"""

import csv
import io
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .build import BuildError

TYPE_MAP = {"INTEGER": pa.int64(), "TEXT": pa.string()}

CSV_README = """Feyod dataset - CSV export
==========================

One CSV file per table of the Feyod dataset (see LICENSE: CC0 1.0).

Format: UTF-8 (no BOM), comma-separated, RFC 4180 quoting, first row is the
header, an empty field means NULL.

Opening in Excel: do not double-click the file (Excel may guess the wrong
encoding and garble names such as "Ståle"). Instead use
Data -> From Text/CSV, choose "65001: Unicode (UTF-8)" as file origin and
comma as delimiter, then Load.
"""

BATCH = 50_000


def _columns(conn, table, wanted):
    info = conn.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
    if not info:
        raise BuildError(f"table {table!r} not found in database")
    declared = {r[1]: (r[2] or "").upper() for r in info}
    missing = [c for c in wanted if c not in declared]
    if missing:
        raise BuildError(f"table {table!r}: columns {missing} missing from database")
    return declared


def _arrow_schema(table, wanted, declared):
    fields = []
    for col in wanted:
        typ = TYPE_MAP.get(declared[col])
        if typ is None:
            raise BuildError(
                f"table {table!r} column {col!r}: unsupported SQLite type "
                f"{declared[col]!r}"
            )
        fields.append(pa.field(col, typ, nullable=True))
    return pa.schema(fields)


def _select(table, wanted):
    cols = ", ".join(f'"{c}"' for c in wanted)
    return f'SELECT {cols} FROM "{table}"'


def export_parquet(conn, out_dir, expected_schema) -> list:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for table, wanted in expected_schema.items():
        wanted = list(wanted)
        declared = _columns(conn, table, wanted)
        schema = _arrow_schema(table, wanted, declared)
        path = out_dir / f"{table}.parquet"
        cur = conn.execute(_select(table, wanted))
        with pq.ParquetWriter(path, schema, compression="zstd") as writer:
            wrote = False
            while True:
                rows = cur.fetchmany(BATCH)
                if not rows:
                    break
                cols = list(zip(*rows))
                arrays = [
                    pa.array(cols[i], type=schema.field(i).type)
                    for i in range(len(wanted))
                ]
                writer.write_table(pa.Table.from_arrays(arrays, schema=schema))
                wrote = True
            if not wrote:
                writer.write_table(schema.empty_table())
        written.append(path)
    return written


def _csv_text(conn, table, wanted) -> str:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(wanted)
    for row in conn.execute(_select(table, wanted)):
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def export_csv_zip(conn, zip_path, expected_schema, license_path) -> Path:
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    texts = {}
    for table, wanted in expected_schema.items():
        wanted = list(wanted)
        _columns(conn, table, wanted)
        texts[f"{table}.csv"] = _csv_text(conn, table, wanted)
    license_text = Path(license_path).read_text(encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in texts.items():
            zf.writestr(name, text.encode("utf-8"))
        zf.writestr("LICENSE", license_text.encode("utf-8"))
        zf.writestr("README.txt", CSV_README.encode("utf-8"))
    return zip_path
