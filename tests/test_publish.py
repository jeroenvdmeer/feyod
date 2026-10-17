import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from feyod_formats import __main__ as cli
from feyod_formats import build
from feyod_formats import publish

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "hf" / "README.md"

MANIFEST = {
    "source_sha": "abc123",
    "build_date": "2026-10-14",
    "row_counts": {"matches": 3, "players": 5},
    "total_rows": 8,
}


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m
    return yaml.safe_load(m.group(1))


def test_render_card_fills_placeholders():
    out = publish.render_card(CARD.read_text(encoding="utf-8"), MANIFEST)
    assert "{{" not in out
    assert "abc123" in out and "2026-10-14" in out
    assert "| matches | 3 |" in out


def test_render_card_fails_on_leftover_placeholder():
    with pytest.raises(publish.PublishError, match="UNKNOWN"):
        publish.render_card("x {{UNKNOWN}} {{SOURCE_SHA}}", MANIFEST)


@pytest.fixture
def built(mini_sql_path, tmp_path):
    out = tmp_path / "build"
    rc = cli.main(
        ["build", "--sql", str(mini_sql_path), "--out", str(out), "--source-sha", "deadbeef"]
    )
    assert rc == 0
    return out


class FakeApi:
    def __init__(self):
        self.calls = []

    def upload_folder(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_hf_calls_api_strictly(built):
    api = FakeApi()
    publish.upload_hf(built / "hf", "msg", "tok", api=api)
    assert api.calls == [
        {
            "repo_id": "jeroenvdmeer/feyod",
            "repo_type": "dataset",
            "folder_path": str(built / "hf"),
            "commit_message": "msg",
            "delete_patterns": ["*.parquet", "*.db", "*.sql"],
            "token": "tok",
        }
    ]


@pytest.mark.parametrize("token", [None, "", "   "])
def test_upload_hf_rejects_missing_token(tmp_path, token):
    api = FakeApi()
    with pytest.raises(publish.PublishError, match="HF_TOKEN"):
        publish.upload_hf(tmp_path, "msg", token, api=api)
    assert api.calls == []


def test_upload_hf_kwargs_exist_on_installed_hfapi():
    import inspect

    from huggingface_hub import HfApi

    params = inspect.signature(HfApi.upload_folder).parameters
    for k in (
        "repo_id",
        "repo_type",
        "folder_path",
        "commit_message",
        "delete_patterns",
        "token",
    ):
        assert k in params


def test_release_notes():
    notes = publish.release_notes(MANIFEST)
    assert "abc123" in notes and "2026-10-14" in notes
    assert "matches" in notes and "5" in notes
    base = "https://github.com/jeroenvdmeer/feyod/releases/latest/download/"
    for a in ("feyod.db", "feyod-csv.zip", "feyod.sql"):
        assert base + a in notes


def test_build_end_to_end_tree(built):
    hf = built / "hf"
    names = sorted(p.name for p in hf.iterdir())
    tables = json.loads(
        (ROOT / "schema" / "expected_schema.json").read_text(encoding="utf-8")
    )
    assert names == sorted([f"{t}.parquet" for t in tables] + ["feyod.db", "README.md"])
    with zipfile.ZipFile(built / "feyod-csv.zip") as zf:
        assert "LICENSE" in zf.namelist()
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha"] == "deadbeef"
    assert (built / "release-notes.md").exists()


def test_rendered_card_frontmatter(built):
    text = (built / "hf" / "README.md").read_text(encoding="utf-8")
    assert "{{" not in text
    fm = frontmatter(text)
    assert fm["license"] == "cc0-1.0"
    assert len(fm["configs"]) == 9
    defaults = [c["config_name"] for c in fm["configs"] if c.get("default") is True]
    assert defaults == ["matches"]
    for c in fm["configs"]:
        assert (built / "hf" / c["data_files"]).exists()


def test_build_default_source_sha(mini_sql_path, tmp_path):
    out = tmp_path / "b"
    assert cli.main(["build", "--sql", str(mini_sql_path), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha"] == "unknown"


def test_build_error_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.sql"
    bad.write_text("THIS IS NOT SQL;", encoding="utf-8")
    rc = cli.main(["build", "--sql", str(bad), "--out", str(tmp_path / "o")])
    assert rc == 1
    assert "loading" in capsys.readouterr().err


def test_upload_hf_cli_missing_token_exits_1(built, monkeypatch, capsys):
    tmp_path = built
    monkeypatch.delenv("HF_TOKEN", raising=False)
    rc = cli.main(["upload-hf", "--out", str(tmp_path), "--commit-message", "m"])
    assert rc == 1
    assert "HF_TOKEN" in capsys.readouterr().err


def test_upload_hf_cli_uses_env_token(built, monkeypatch):
    tmp_path = built
    monkeypatch.setenv("HF_TOKEN", "secret")
    seen = {}

    def fake(folder, msg, token, api=None):
        seen.update(f=folder, m=msg, t=token)

    monkeypatch.setattr(publish, "upload_hf", fake)
    assert cli.main(["upload-hf", "--out", str(tmp_path), "--commit-message", "m"]) == 0
    assert seen["t"] == "secret" and seen["m"] == "m"
    assert Path(seen["f"]) == tmp_path / "hf"


def test_upload_hf_cli_missing_folder_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_TOKEN", "secret")
    rc = cli.main(["upload-hf", "--out", str(tmp_path), "--commit-message", "m"])
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_module_entrypoint_help():
    r = subprocess.run(
        [sys.executable, "-m", "feyod_formats", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0


def test_render_card_placeholder_across_newline():
    with pytest.raises(publish.PublishError):
        publish.render_card("a {{FOO\nBAR}} b", MANIFEST)


def _spy_api(monkeypatch):
    api = FakeApi()
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "HfApi", lambda *a, **k: api)
    return api


def _refused(folder, api):
    with pytest.raises(build.BuildError):
        publish.upload_hf(folder, "m", "tok", api=api)
    assert api.calls == []


def test_upload_refused_empty_folder(tmp_path):
    (tmp_path / "hf").mkdir()
    _refused(tmp_path / "hf", FakeApi())


def test_upload_refused_missing_matches(built):
    (built / "hf" / "matches.parquet").unlink()
    _refused(built / "hf", FakeApi())


def test_upload_refused_stale_sql(built):
    (built / "hf" / "feyod.sql").write_text("x", encoding="utf-8")
    _refused(built / "hf", FakeApi())


def test_upload_refused_empty_file(built):
    (built / "hf" / "goals.parquet").write_bytes(b"")
    _refused(built / "hf", FakeApi())


def test_upload_refused_without_manifest(built):
    (built / "manifest.json").unlink()
    _refused(built / "hf", FakeApi())


def test_upload_refused_db_with_extra_column(built):
    import sqlite3

    con = sqlite3.connect(built / "hf" / "feyod.db")
    con.execute("ALTER TABLE matches ADD COLUMN delpherSourceUrl TEXT")
    con.commit()
    con.close()
    _refused(built / "hf", FakeApi())


def _leaky_sql(mini_sql_path, tmp_path):
    text = mini_sql_path.read_text(encoding="utf-8")
    bad = tmp_path / "leaky.sql"
    bad.write_text(
        text + "\nALTER TABLE matches ADD COLUMN delpherSourceUrl TEXT;\n",
        encoding="utf-8",
    )
    return bad


def test_failed_build_fresh_out_leaves_nothing(mini_sql_path, tmp_path, monkeypatch, capsys):
    bad = _leaky_sql(mini_sql_path, tmp_path)
    out = tmp_path / "fresh"
    assert cli.main(["build", "--sql", str(bad), "--out", str(out)]) == 1
    assert not (out / "hf").exists()
    assert not list(out.glob(".staging-*"))
    api = _spy_api(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "t")
    assert cli.main(["upload-hf", "--out", str(out), "--commit-message", "m"]) == 1
    assert api.calls == []


def test_failed_build_over_good_build_removes_old(built, mini_sql_path, tmp_path, monkeypatch):
    bad = _leaky_sql(mini_sql_path, tmp_path)
    assert (built / "hf").exists()
    assert cli.main(["build", "--sql", str(bad), "--out", str(built)]) == 1
    for name in ("hf", "feyod-csv.zip", "manifest.json", "release-notes.md"):
        assert not (built / name).exists()
    assert not list(built.glob(".staging-*"))
    api = _spy_api(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "t")
    assert cli.main(["upload-hf", "--out", str(built), "--commit-message", "m"]) == 1
    assert api.calls == []
