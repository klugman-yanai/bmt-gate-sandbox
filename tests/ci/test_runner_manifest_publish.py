"""filter_upload_matrix manifest_only legs when skip_missing_runner_artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from ci.runner import RunnerManager

pytestmark = pytest.mark.unit


def test_filter_manifest_only_when_skip_missing_no_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "fake-bucket")
    monkeypatch.setenv("HEAD_SHA", "abc123")
    monkeypatch.setenv("BMT_CI_RUN_ID", "55")
    monkeypatch.setenv("SKIP_MISSING_RUNNER_ARTIFACTS", "true")
    monkeypatch.setenv(
        "RUNNER_MATRIX",
        json.dumps(
            {
                "include": [
                    {
                        "configure": "SK_gcc_Release",
                        "preset": "sk_gcc_release",
                        "project": "sk",
                        "bmt_id": "sk_gcc_release",
                        "binary_dir": "build/SK/gcc_Release",
                    }
                ]
            }
        ),
    )
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", "[]")

    with (
        patch.object(RunnerManager, "_w", return_value=None),
        patch("ci.runner.gcs.download_json", return_value=(None, "missing")),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    assert "matrix_publish<<PUBLISH_EOF" in text
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["project"] == "sk"
    assert rows[0]["publish_mode"] == "manifest_only"
    assert rows[0]["bmt_supported"] == "true"

    need = text.split("matrix_need_upload<<FILTER_EOF\n", 1)[1].split("\nFILTER_EOF\n", 1)[0]
    need_obj = json.loads(need)
    assert len(need_obj["include"]) == 1


def test_filter_binary_when_artifact_present_with_skip_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "fake-bucket")
    monkeypatch.setenv("HEAD_SHA", "abc123")
    monkeypatch.setenv("BMT_CI_RUN_ID", "55")
    monkeypatch.setenv("SKIP_MISSING_RUNNER_ARTIFACTS", "true")
    monkeypatch.setenv(
        "RUNNER_MATRIX",
        json.dumps(
            {
                "include": [
                    {
                        "configure": "SK_gcc_Release",
                        "preset": "sk_gcc_release",
                        "project": "sk",
                        "bmt_id": "sk_gcc_release",
                        "binary_dir": "build/SK/gcc_Release",
                    }
                ]
            }
        ),
    )
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", json.dumps(["runner-sk_gcc_release"]))

    with (
        patch.object(RunnerManager, "_w", return_value=None),
        patch("ci.runner.gcs.download_json", return_value=(None, "missing")),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["publish_mode"] == "binary"


def test_dev_manifest_payload_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "sk_gcc_release")
    monkeypatch.setenv("SOURCE_REF", "deadbeef")
    monkeypatch.setenv("GCS_BUCKET", "my-bucket")
    monkeypatch.setenv("BMT_CI_RUN_ID", "99")
    monkeypatch.setenv("GCP_PROJECT", "p")
    monkeypatch.setenv("GCP_SA_EMAIL", "sa@p.iam.gserviceaccount.com")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "prov")

    uploaded: dict[str, object] = {}

    def fake_upload(uri: str, payload: dict) -> None:
        uploaded["uri"] = uri
        uploaded["payload"] = payload

    with patch("ci.runner.gcs.upload_json", side_effect=fake_upload):
        RunnerManager.from_env().upload_dev_publish_manifest()

    assert uploaded["uri"] == ("gs://my-bucket/_workflow/dev_publish_manifest/99/sk__sk_gcc_release.json")
    p = uploaded["payload"]
    assert isinstance(p, dict)
    assert p["kind"] == "bmt_ci_dev_publish_manifest"
    assert p["would_publish"]["kardome_runner"] == "gs://my-bucket/projects/sk/kardome_runner"
    assert p["project"] == "sk"
