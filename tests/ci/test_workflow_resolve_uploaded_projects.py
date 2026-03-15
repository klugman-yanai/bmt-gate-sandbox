from __future__ import annotations

import json
from pathlib import Path

from ci import gcs
from ci.runner import RunnerManager


def test_resolve_uploaded_projects_uses_uploaded_markers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    monkeypatch.setattr(
        gcs,
        "list_prefix",
        lambda _prefix: [
            "gs://bucket-a/_workflow/uploaded/12345/sk.json",
            "gs://bucket-a/_workflow/uploaded/12345/qa.json",
        ],
    )
    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "not found"))

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

    monkeypatch.setattr(gcs, "list_prefix", lambda _prefix: [])

    def fake_download_json(uri: str):
        # Actual path: projects/{project}/runner_meta.json or runner_latest_meta.json (VM bmt_jobs)
        if "projects/sk/runner_meta.json" in uri or "projects/sk/runner_latest_meta.json" in uri:
            return ({"project": "sk", "preset": "sk_gcc_release"}, None)
        return (None, "404")

    monkeypatch.setattr(gcs, "download_json", fake_download_json)

    RunnerManager.from_env().resolve_uploaded_projects()

    accepted = json.loads(Path("accepted.txt").read_text(encoding="utf-8"))
    assert accepted == ["sk"]
    assert 'accepted_projects=["sk"]' in out.read_text(encoding="utf-8")
