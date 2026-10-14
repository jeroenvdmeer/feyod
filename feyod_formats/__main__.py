"""CLI: `build` (all artifacts, no network) and `upload-hf` (external publication)."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import build, export, publish

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "expected_schema.json"
CARD_TEMPLATE = ROOT / "hf" / "README.md"
LICENSE = ROOT / "LICENSE"


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


ARTIFACTS = ("hf", "feyod-csv.zip", "manifest.json", "release-notes.md")


def _build_into(args, stage: Path) -> int:
    hf = stage / "hf"
    hf.mkdir()
    expected = json.loads(SCHEMA.read_text(encoding="utf-8"))
    conn = build.load_dump(args.sql, hf / "feyod.db")
    try:
        counts = build.run_gate(conn, expected)
        # Rewrite the file so dropped tables/columns leave no bytes behind.
        conn.execute("VACUUM")
        export.export_parquet(conn, hf, expected)
        export.export_csv_zip(conn, stage / "feyod-csv.zip", expected, LICENSE)
    finally:
        conn.close()
    build_date = datetime.now(timezone.utc).date().isoformat()
    manifest_path = stage / "manifest.json"
    build.write_manifest(manifest_path, counts, args.source_sha, build_date)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    card = publish.render_card(CARD_TEMPLATE.read_text(encoding="utf-8"), manifest)
    (hf / "README.md").write_text(card, encoding="utf-8")
    (stage / "release-notes.md").write_text(
        publish.release_notes(manifest), encoding="utf-8"
    )
    return sum(counts.values()), len(counts)


def cmd_build(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=out))
    try:
        rows, tables = _build_into(args, stage)
        for name in ARTIFACTS:
            _remove(out / name)
        for name in ARTIFACTS:
            shutil.move(str(stage / name), str(out / name))
    except BaseException:
        # never leave a stale or partial output that upload-hf could publish
        for name in ARTIFACTS:
            _remove(out / name)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print(f"built {rows} rows in {tables} tables into {out}")
    return 0


def cmd_upload_hf(args) -> int:
    folder = Path(args.out) / "hf"
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
