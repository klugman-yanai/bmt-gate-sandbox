from __future__ import annotations

import json
from pathlib import Path

from bmt_gate import gcs
from bmt_gate.runner import RunnerManager


def test_resolve_uploaded_projects_uses_uploaded_markers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    monkeypatch.setattr(
        gcs,
        "list_prefix",
        lambda prefix: [
            "gs://bucket-a/_workflow/uploaded/12345/sk.json",
            "gs://bucket-a/_workflow/uploaded/12345/qa.json",
        ],
    )
    monkeypatch.setattr(gcs, "download_json", lambda uri: (None, "not found"))

    RunnerManager.from_env().resolve_uploaded_projects()

    accepted = json.loads(Path("accepted.txt").read_text(encoding="utf-8"))
    assert accepted == ["qa", "sk"]
    assert 'accepted_projects=["qa", "sk"]' in out.read_text(encoding="utf-8")


def test_resolve_uploaded_projects_accepts_preseeded_bucket_runner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_RUN_ID", "22940217333")
    monkeypatch.setenv("GCS_BUCKET", "train-kws-202311-bmt-gate")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv(
        "RUNNER_MATRIX",
        json.dumps(
            {
                "include": [
                    {"project": "sk", "preset": "sk_gcc_release"},
                    {"project": "missing", "preset": "missing_release"},
                ]
            }
        ),
    )

    monkeypatch.setattr(gcs, "list_prefix", lambda prefix: [])

    def fake_download_json(uri: str):
        if uri.endswith("/sk/runners/sk_gcc_release/runner_meta.json"):
            return ({"project": "sk", "preset": "sk_gcc_release"}, None)
        return (None, "404")

    monkeypatch.setattr(gcs, "download_json", fake_download_json)

    RunnerManager.from_env().resolve_uploaded_projects()

    accepted = json.loads(Path("accepted.txt").read_text(encoding="utf-8"))
    assert accepted == ["sk"]
    assert 'accepted_projects=["sk"]' in out.read_text(encoding="utf-8")
