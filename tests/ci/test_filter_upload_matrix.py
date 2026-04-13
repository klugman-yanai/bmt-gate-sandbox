"""Tests for RunnerManager.filter_upload_matrix — focus on the no-artifact / bucket-runner path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci import gcs
from ci.runner import RunnerManager

pytestmark = pytest.mark.unit

_RUNNER_MATRIX = json.dumps(
    {
        "include": [
            {"project": "sk", "preset": "sk_gcc_release"},
        ]
    }
)


def _setup_env(monkeypatch, tmp_path: Path, *, available_artifacts: str = "[]") -> Path:
    out = tmp_path / "github_output.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("GITHUB_RUN_ID", "99999")
    monkeypatch.setenv("BMT_CI_RUN_ID", "99999")
    monkeypatch.setenv("RUNNER_MATRIX", _RUNNER_MATRIX)
    monkeypatch.setenv("HEAD_SHA", "abc1234" * 5 + "abcd")
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", available_artifacts)
    # Ensure skip/preseeded flags are off
    monkeypatch.delenv("BMT_SKIP_PUBLISH_RUNNERS", raising=False)
    monkeypatch.delenv("BMT_RUNNERS_PRESEEDED_IN_GCS", raising=False)
    return out


def _read_output(out: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    content = out.read_text(encoding="utf-8")
    # Parse multi-line heredoc outputs like: key<<EOF\nval\nEOF
    import re

    for m in re.finditer(r"(\w+)<<\w+\n(.+?)\n\w+", content, re.DOTALL):
        result[m.group(1)] = m.group(2).strip()
    # Also parse simple key=value
    for line in content.splitlines():
        if "<<" not in line and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def test_filter_upload_matrix_skips_sk_when_no_artifacts_and_runner_binary_in_gcs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no GitHub artifacts and kardome_runner exists in GCS, skip publish and write marker."""
    monkeypatch.chdir(tmp_path)
    out = _setup_env(monkeypatch, tmp_path)

    # No runner_meta.json, but binary exists
    written: list[str] = []

    def fake_download_json(uri: str):
        return (None, "404")

    def fake_object_exists(uri: str) -> bool:
        return "projects/sk/kardome_runner" in uri

    def fake_write_object(uri: str, data: object) -> None:
        written.append(uri)

    monkeypatch.setattr(gcs, "download_json", fake_download_json)
    monkeypatch.setattr(gcs, "object_exists", fake_object_exists)
    monkeypatch.setattr(gcs, "write_object", fake_write_object)

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    assert outputs["matrix_publish_keys"] == "[]", (
        "sk should NOT be in publish matrix when runner binary is in GCS"
    )
    assert outputs["matrix_need_upload_keys"] == "[]"

    # Upload marker must have been written
    assert any("_workflow/uploaded/99999/sk.json" in u for u in written), (
        f"Expected upload marker written for sk; got: {written}"
    )


def test_filter_upload_matrix_adds_to_publish_when_no_artifacts_and_no_runner_in_gcs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no GitHub artifacts and no runner in GCS at all, sk goes into publish matrix."""
    monkeypatch.chdir(tmp_path)
    out = _setup_env(monkeypatch, tmp_path)

    def fake_download_json(uri: str):
        return (None, "404")

    def fake_object_exists(uri: str) -> bool:
        return False  # nothing in bucket

    monkeypatch.setattr(gcs, "download_json", fake_download_json)
    monkeypatch.setattr(gcs, "object_exists", fake_object_exists)
    # write_object should not be called — no need to monkeypatch

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    pub = json.loads(outputs["matrix_publish"])
    projects = [e["project"] for e in pub.get("include", [])]
    assert "sk" in projects, "sk should be in publish matrix when no runner in GCS"


def test_filter_upload_matrix_meta_sha_match_still_skips_without_binary_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing path: meta present with matching source_ref still skips (regression guard)."""
    monkeypatch.chdir(tmp_path)
    head_sha = "deadbeef" * 5
    out = _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HEAD_SHA", head_sha)

    written: list[str] = []

    def fake_download_json(uri: str):
        if "runner_meta.json" in uri or "runner_latest_meta.json" in uri:
            return ({"source_ref": head_sha, "project": "sk"}, None)
        return (None, "404")

    monkeypatch.setattr(gcs, "download_json", fake_download_json)
    monkeypatch.setattr(gcs, "write_object", lambda u, _: written.append(u))

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    assert outputs["matrix_publish_keys"] == "[]"
    assert any("sk.json" in u for u in written)
