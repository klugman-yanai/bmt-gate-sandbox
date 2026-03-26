"""filter_upload_matrix manifest_only legs when skip_missing_runner_artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from bmtgate.matrix.runner import RunnerManager

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
        patch("bmtgate.matrix.runner.gcs.download_json", return_value=(None, "missing")),
        patch(
            "bmtgate.matrix.runner.gcs.list_prefix",
            return_value=["gs://fake-bucket/projects/sk/bmts/false_rejects/bmt.json"],
        ),
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
        patch("bmtgate.matrix.runner.gcs.download_json", return_value=(None, "missing")),
        patch(
            "bmtgate.matrix.runner.gcs.list_prefix",
            return_value=["gs://fake-bucket/projects/sk/bmts/false_rejects/bmt.json"],
        ),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["publish_mode"] == "binary"


def test_filter_dev_omit_presets_without_bucket_bmts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev skip_missing: only projects with objects under projects/<p>/bmts/ enter the matrix."""
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
                    },
                    {
                        "configure": "WOVEN_gcc_Release",
                        "preset": "woven_gcc_release",
                        "project": "woven",
                        "bmt_id": "woven_gcc_release",
                        "binary_dir": "build/WOVEN/gcc_Release",
                    },
                ]
            }
        ),
    )
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", "[]")

    def fake_list(uri: str) -> list[str]:
        if "/projects/sk/bmts/" in uri:
            return ["gs://fake-bucket/projects/sk/bmts/false_rejects/bmt.json"]
        return []

    with (
        patch.object(RunnerManager, "_w", return_value=None),
        patch("bmtgate.matrix.runner.gcs.download_json", return_value=(None, "missing")),
        patch("bmtgate.matrix.runner.gcs.list_prefix", side_effect=fake_list),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["project"] == "sk"

    omit_payload = text.split("matrix_publish_omitted<<OMIT_EOF\n", 1)[1].split("\nOMIT_EOF\n", 1)[0]
    omit = json.loads(omit_payload)
    assert len(omit["include"]) == 1
    assert omit["include"][0]["project"] == "woven"
    assert omit["include"][0]["shadow"] is True


def test_filter_dev_synthetic_unsupported_without_bucket_when_flag_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "fake-bucket")
    monkeypatch.setenv("HEAD_SHA", "abc123")
    monkeypatch.setenv("BMT_CI_RUN_ID", "55")
    monkeypatch.setenv("SKIP_MISSING_RUNNER_ARTIFACTS", "true")
    monkeypatch.setenv("BMT_DEV_APPEND_UNSUPPORTED_RUNNER_LEG", "true")
    monkeypatch.setenv(
        "RUNNER_MATRIX",
        json.dumps(
            {
                "include": [
                    {
                        "configure": "CI_DEV_UNSUPPORTED_gcc_Release",
                        "preset": "ci_dev_unsupported_gcc_release",
                        "project": "ci_dev_unsupported",
                        "bmt_id": "ci_dev_unsupported_gcc_release",
                        "binary_dir": "build/X/gcc_Release",
                    },
                ]
            }
        ),
    )
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", "[]")

    with (
        patch.object(RunnerManager, "_w", return_value=None),
        patch("bmtgate.matrix.runner.gcs.download_json", return_value=(None, "missing")),
        patch("bmtgate.matrix.runner.gcs.list_prefix", return_value=[]),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["project"] == "ci_dev_unsupported"
    assert rows[0]["publish_mode"] == "manifest_only"


def test_filter_production_matrix_only_binary_supported_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When skip_missing is off, matrix_publish is binary+supported and omits no-bucket-bmts legs."""
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "fake-bucket")
    monkeypatch.setenv("HEAD_SHA", "abc123")
    monkeypatch.setenv("BMT_CI_RUN_ID", "55")
    monkeypatch.delenv("SKIP_MISSING_RUNNER_ARTIFACTS", raising=False)
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
                    },
                    {
                        "configure": "ZZUNSUPPORTED_gcc_Release",
                        "preset": "zzunsupported_gcc_release",
                        "project": "zzunsupported",
                        "bmt_id": "zzunsupported_gcc_release",
                        "binary_dir": "build/ZZ/gcc_Release",
                    },
                ]
            }
        ),
    )
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", json.dumps(["runner-sk_gcc_release", "runner-zzunsupported_gcc_release"]))

    def fake_list(uri: str) -> list[str]:
        if "/projects/sk/bmts/" in uri:
            return ["gs://fake-bucket/projects/sk/bmts/false_rejects/bmt.json"]
        return []

    with (
        patch.object(RunnerManager, "_w", return_value=None),
        patch("bmtgate.matrix.runner.gcs.download_json", return_value=(None, "missing")),
        patch("bmtgate.matrix.runner.gcs.list_prefix", side_effect=fake_list),
    ):
        RunnerManager.from_env().filter_upload_matrix()

    text = out.read_text(encoding="utf-8")
    payload = text.split("matrix_publish<<PUBLISH_EOF\n", 1)[1].split("\nPUBLISH_EOF\n", 1)[0]
    pub = json.loads(payload)
    rows = pub["include"]
    assert len(rows) == 1
    assert rows[0]["project"] == "sk"
    assert rows[0]["publish_mode"] == "binary"

    omit_payload = text.split("matrix_publish_omitted<<OMIT_EOF\n", 1)[1].split("\nOMIT_EOF\n", 1)[0]
    omit = json.loads(omit_payload)
    assert len(omit["include"]) == 1
    assert omit["include"][0]["project"] == "zzunsupported"
    assert omit["include"][0]["shadow"] is True


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

    with patch("bmtgate.matrix.runner.gcs.upload_json", side_effect=fake_upload):
        RunnerManager.from_env().upload_dev_publish_manifest()

    assert uploaded["uri"] == ("gs://my-bucket/_workflow/dev_publish_manifest/99/sk__sk_gcc_release.json")
    raw_p = uploaded["payload"]
    assert isinstance(raw_p, dict)
    p = cast(dict[str, Any], raw_p)
    assert p["kind"] == "bmt_ci_dev_publish_manifest"
    assert p["would_publish"]["kardome_runner"] == "gs://my-bucket/projects/sk/kardome_runner"
    assert p["project"] == "sk"
