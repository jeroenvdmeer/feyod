"""Publication helpers: HF dataset card rendering, HF upload, release notes."""

import json
import re
import sqlite3
from pathlib import Path

from .build import BuildError, check_schema

REPO_ID = "jeroenvdmeer/feyod"
REPO_TYPE = "dataset"
# Make the HF repo a mirror of build/hf/ (also removes the obsolete feyod.sql).
DELETE_PATTERNS = ["*.parquet", "*.db", "*.sql"]
RELEASE_BASE = "https://github.com/jeroenvdmeer/feyod/releases/latest/download/"
RELEASE_ASSETS = ("feyod.db", "feyod-csv.zip", "feyod.sql")

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "expected_schema.json"
_PLACEHOLDER = re.compile(r"\{\{[\s\S]*?\}\}")


class PublishError(BuildError):
    """Publishing was refused or failed; nothing (more) may be published."""


def _counts_table(row_counts) -> str:
    lines = ["| Table | Rows |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in sorted(row_counts.items())]
    return "\n".join(lines)


def render_card(template: str, manifest: dict) -> str:
    values = {
        "{{ROW_COUNTS_TABLE}}": _counts_table(manifest["row_counts"]),
        "{{SOURCE_SHA}}": str(manifest["source_sha"]),
        "{{BUILD_DATE}}": str(manifest["build_date"]),
    }
    out = template
    for key, val in values.items():
        out = out.replace(key, val)
    left = _PLACEHOLDER.findall(out)
    if left:
        raise PublishError(f"dataset card has unfilled placeholder(s): {sorted(set(left))}")
    return out


def verify_hf_folder(folder) -> None:
    """Refuse anything but a complete, schema-clean output of a successful build."""
    folder = Path(folder)
    if not folder.is_dir():
        raise PublishError(f"upload folder {folder} does not exist")
    expected = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    want = {f"{t}.parquet" for t in expected} | {"feyod.db", "README.md"}
    have = {p.name for p in folder.iterdir()}
    if have != want or any(not p.is_file() for p in folder.iterdir()):
        raise PublishError(
            f"{folder} is not an exact build output: missing {sorted(want - have)}, "
            f"unexpected {sorted(have - want)}"
        )
    empty = [n for n in sorted(want) if (folder / n).stat().st_size == 0]
    if empty:
        raise PublishError(f"empty files in {folder}: {empty}")
    if not (folder.parent / "manifest.json").is_file():
        raise PublishError(f"{folder.parent / 'manifest.json'} missing; run `build` first")
    uri = (folder / "feyod.db").resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            check_schema(conn, expected)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise PublishError(f"feyod.db unreadable: {exc}") from exc


def upload_hf(folder, commit_message, token, api=None) -> None:
    """Upload `folder` to the HF dataset repo, mirroring it (D5). Errors propagate."""
    if not token or not str(token).strip():
        raise PublishError("HF_TOKEN is missing or empty; refusing to upload")
    verify_hf_folder(folder)
    if api is None:
        from huggingface_hub import HfApi

        api = HfApi()
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
        folder_path=str(folder),
        commit_message=commit_message,
        delete_patterns=list(DELETE_PATTERNS),
        token=token,
    )


def release_notes(manifest: dict) -> str:
    lines = [
        "Automatically generated from the latest `feyod.sql`.",
        "",
        f"- Source commit: `{manifest['source_sha']}`",
        f"- Build date: {manifest['build_date']}",
        "",
        "## Row counts",
        "",
        _counts_table(manifest["row_counts"]),
        "",
        "## Stable download links",
        "",
    ]
    lines += [f"- {RELEASE_BASE}{a}" for a in RELEASE_ASSETS]
    return "\n".join(lines) + "\n"
