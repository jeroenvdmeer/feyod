"""CLI: `build` (all artifacts, no network) and `upload-hf` (external publication)."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import build, export, publish

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "expected_schema.json"
CARD_TEMPLATE = ROOT / "hf" / "README.md"
LICENSE = ROOT / "LICENSE"


def cmd_build(args) -> int:
    out = Path(args.out)
    hf = out / "hf"
    out.mkdir(parents=True, exist_ok=True)
    hf.mkdir(parents=True, exist_ok=True)
    expected = json.loads(SCHEMA.read_text(encoding="utf-8"))
    db_path = hf / "feyod.db"
    conn = build.load_dump(args.sql, db_path)
    try:
        counts = build.run_gate(conn, expected)
        export.export_parquet(conn, hf, expected)
        export.export_csv_zip(conn, out / "feyod-csv.zip", expected, LICENSE)
    finally:
        conn.close()
    build_date = datetime.now(timezone.utc).date().isoformat()
    manifest_path = out / "manifest.json"
    build.write_manifest(manifest_path, counts, args.source_sha, build_date)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    card = publish.render_card(CARD_TEMPLATE.read_text(encoding="utf-8"), manifest)
    (hf / "README.md").write_text(card, encoding="utf-8")
    (out / "release-notes.md").write_text(
        publish.release_notes(manifest), encoding="utf-8"
    )
    print(f"built {sum(counts.values())} rows in {len(counts)} tables into {out}")
    return 0


def cmd_upload_hf(args) -> int:
    folder = Path(args.out) / "hf"
    if not folder.is_dir():
        raise publish.PublishError(f"{folder} not found; run `build` first")
    publish.upload_hf(folder, args.commit_message, os.environ.get("HF_TOKEN"))
    print(f"uploaded {folder} to {publish.REPO_ID}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="feyod_formats")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build all artifacts from feyod.sql")
    b.add_argument("--sql", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--source-sha", default="unknown")
    b.set_defaults(func=cmd_build)
    u = sub.add_parser("upload-hf", help="upload <out>/hf to Hugging Face")
    u.add_argument("--out", required=True)
    u.add_argument("--commit-message", required=True)
    u.set_defaults(func=cmd_upload_hf)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except build.BuildError as exc:  # PublishError is a BuildError
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
