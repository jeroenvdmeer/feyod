from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "publish-formats.yml"


def load():
    text = WF.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    # PyYAML parses the bare key `on` as boolean True.
    triggers = doc.get("on", doc.get(True))
    return text, doc, triggers


def run_steps(job):
    return [s["run"] for s in job["steps"] if "run" in s]


def test_parses_and_has_jobs():
    _, doc, _ = load()
    assert set(doc["jobs"]) == {"test", "publish"}


def test_publish_needs_test():
    _, doc, _ = load()
    assert doc["jobs"]["publish"]["needs"] == "test"


def test_triggers():
    _, _, t = load()
    assert t["push"]["branches"] == ["main"]
    assert "feyod.sql" in t["push"]["paths"]
    for p in ("LICENSE", "tests/**", "pytest.ini"):
        assert p in t["push"]["paths"]
    assert "pull_request" in t
    assert "workflow_dispatch" in t


def test_publish_only_on_main_push_or_dispatch():
    _, doc, _ = load()
    cond = doc["jobs"]["publish"]["if"]
    assert "refs/heads/main" in cond
    assert "push" in cond and "workflow_dispatch" in cond
    assert "pull_request" not in cond


def test_no_event_or_secret_interpolation_in_run():
    _, doc, _ = load()
    for job in doc["jobs"].values():
        for run in run_steps(job):
            assert "${{ github.event" not in run
            assert "${{ secrets" not in run
            assert "${{" not in run  # every expression goes through env:


def test_hf_token_only_via_env():
    text, doc, _ = load()
    assert text.count("secrets.HF_TOKEN") == 1
    hits = [
        s
        for job in doc["jobs"].values()
        for s in job["steps"]
        if "secrets.HF_TOKEN" in str(s.get("env", {}))
    ]
    assert len(hits) == 1 and "run" in hits[0]


def test_concurrency_only_on_publish_job():
    _, doc, _ = load()
    assert "concurrency" not in doc
    assert "concurrency" not in doc["jobs"]["test"]
    c = doc["jobs"]["publish"]["concurrency"]
    assert c["group"] == "publish-formats"
    assert c["cancel-in-progress"] is False


def test_checkout_does_not_persist_credentials():
    _, doc, _ = load()
    for job in doc["jobs"].values():
        for s in job["steps"]:
            if s.get("uses", "").startswith("actions/checkout"):
                assert s["with"]["persist-credentials"] is False


def test_hf_commit_message_form_and_release_order():
    _, doc, _ = load()
    runs = run_steps(doc["jobs"]["publish"])
    hf = next(r for r in runs if "upload-hf" in r)
    assert '--commit-message="' in hf
    rel = next(r for r in runs if "gh release" in r)
    assert "build/hf/feyod.db build/feyod-csv.zip feyod.sql --clobber" in rel
    assert rel.index("gh release create") < rel.index("--clobber") < rel.index(
        "gh release edit"
    )
    assert "--latest" in rel[rel.index("gh release edit") :]
    assert runs.index(hf) < runs.index(rel)


def test_permissions_least_privilege():
    _, doc, _ = load()
    assert doc["jobs"]["test"]["permissions"] == {"contents": "read"}
    assert doc["jobs"]["publish"]["permissions"] == {"contents": "write"}
    assert "write" not in str(doc.get("permissions", {}))


def test_actions_pinned_to_verified_tags():
    _, doc, _ = load()
    uses = {
        s["uses"] for j in doc["jobs"].values() for s in j["steps"] if "uses" in s
    }
    assert uses == {"actions/checkout@v7", "actions/setup-python@v7"}


def test_readme_has_stable_download_urls():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    base = "https://github.com/jeroenvdmeer/feyod/releases/latest/download/"
    for name in ("feyod.db", "feyod-csv.zip", "feyod.sql"):
        assert base + name in readme
    assert "https://huggingface.co/datasets/jeroenvdmeer/feyod" in readme
    assert "CC0" in readme
