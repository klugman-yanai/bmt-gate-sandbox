"""Tests for RunnerManager.filter_upload_matrix.

The filter now emits three matrices so the workflow can render two parallel
UI nodes:

- ``matrix_publish``     — supported BMT legs, each tagged
  ``upload_action ∈ {"upload", "skip_in_gcs"}``.
- ``matrix_no_bmt``      — release presets with no cloud BMT plugin.
- ``matrix_need_upload`` — back-compat subset: the ``upload`` rows only.

Every supported leg appears in ``matrix_publish`` regardless of GCS state —
"already in GCS" shows up as a visible ``skip_in_gcs`` row, never as a
silently dropped entry. The previous regression asserted the opposite; that
behavior has been intentionally reversed so the UI always shows the
project-in-cloud legs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kardome_bmt import gcs
from kardome_bmt.runner import RunnerManager

pytestmark = pytest.mark.unit

_RUNNER_MATRIX_SK_ONLY = json.dumps(
    {
        "include": [
            {"project": "sk", "preset": "sk_gcc_release"},
        ]
    }
)

_RUNNER_MATRIX_MIXED = json.dumps(
    {
        "include": [
            {"project": "sk", "preset": "sk_gcc_release"},
            {"project": "hmtc", "preset": "hmtc_gcc_release"},
            {"project": "woven", "preset": "woven_gcc_release"},
        ]
    }
)


def _setup_env(
    monkeypatch,
    tmp_path: Path,
    *,
    available_artifacts: str = "[]",
    runner_matrix: str = _RUNNER_MATRIX_SK_ONLY,
) -> Path:
    out = tmp_path / "github_output.txt"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("GITHUB_RUN_ID", "99999")
    monkeypatch.setenv("BMT_CI_RUN_ID", "99999")
    monkeypatch.setenv("RUNNER_MATRIX", runner_matrix)
    monkeypatch.setenv("HEAD_SHA", "abc1234" * 5 + "abcd")
    monkeypatch.setenv("AVAILABLE_ARTIFACTS", available_artifacts)
    monkeypatch.delenv("BMT_SKIP_PUBLISH_RUNNERS", raising=False)
    monkeypatch.delenv("BMT_RUNNERS_PRESEEDED_IN_GCS", raising=False)
    return out


def _read_output(out: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    content = out.read_text(encoding="utf-8")
    import re

    for m in re.finditer(r"(\w+)<<(\w+)\n(.*?)\n\2", content, re.DOTALL):
        result[m.group(1)] = m.group(3).strip()
    for line in content.splitlines():
        if "<<" not in line and "=" in line:
            k, _, v = line.partition("=")
            if k.strip() and k.strip() not in result:
                result[k.strip()] = v.strip()
    return result


def _sk_publish_row(outputs: dict[str, str]) -> dict:
    pub = json.loads(outputs["matrix_publish"])
    rows = [e for e in pub.get("include", []) if e.get("project") == "sk"]
    assert rows, f"sk should always appear in matrix_publish; got {pub}"
    return rows[0]


def _ensure_local_project_layout(tmp_path: Path, project: str) -> None:
    """Make ``plugins/projects/<project>/project.json`` so ``_project_has_bmt_stage_layout`` returns True."""
    p = tmp_path / "plugins" / "projects" / project
    p.mkdir(parents=True, exist_ok=True)
    (p / "project.json").write_text("{}", encoding="utf-8")


def test_sk_skip_in_gcs_when_no_artifacts_and_runner_binary_in_gcs_new_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No GitHub artifacts + kardome_runner at new GCS layout → sk is `skip_in_gcs` (visible)."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    out = _setup_env(monkeypatch, tmp_path)

    written: list[str] = []
    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "404"))
    monkeypatch.setattr(gcs, "object_exists", lambda uri: "projects/sk/kardome_runner" in uri)
    monkeypatch.setattr(gcs, "write_object", lambda u, _: written.append(u))

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    assert json.loads(outputs["matrix_publish_keys"]) == ["sk|sk_gcc_release"]
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "skip_in_gcs"
    assert row["bmt_supported"] == "true"
    assert row["skip_reason"]
    assert outputs["matrix_need_upload_keys"] == "[]"
    assert any("_workflow/uploaded/99999/sk.json" in u for u in written)


def test_sk_skip_in_gcs_when_no_artifacts_and_runner_binary_in_gcs_old_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Old-layout GCS path (sk/runners/preset/kardome_runner) also classified as `skip_in_gcs`."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    out = _setup_env(monkeypatch, tmp_path)

    written: list[str] = []
    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "404"))
    monkeypatch.setattr(gcs, "object_exists", lambda uri: "sk/runners/sk_gcc_release/kardome_runner" in uri)
    monkeypatch.setattr(gcs, "write_object", lambda u, _: written.append(u))

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "skip_in_gcs"
    assert any("_workflow/uploaded/99999/sk.json" in u for u in written)


def test_sk_upload_when_no_artifacts_and_no_runner_in_gcs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No GitHub artifacts AND nothing in GCS → sk is `upload` (real push required)."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    out = _setup_env(monkeypatch, tmp_path)

    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "404"))
    monkeypatch.setattr(gcs, "object_exists", lambda _uri: False)

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "upload"
    assert row["bmt_supported"] == "true"
    # need_upload shadow carries the `upload` subset (without UI-only fields)
    need = json.loads(outputs["matrix_need_upload"])
    assert [e["project"] for e in need["include"]] == ["sk"]
    assert "upload_action" not in need["include"][0], "need_upload entries are UI-field-free"


def test_sk_skip_in_gcs_when_old_layout_meta_matches_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """runner_latest_meta.json at old layout still triggers `skip_in_gcs` when caller has artifacts."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    head_sha = "deadbeef" * 5
    out = _setup_env(
        monkeypatch,
        tmp_path,
        available_artifacts='["runner-sk_gcc_release"]',
    )
    monkeypatch.setenv("HEAD_SHA", head_sha)

    written: list[str] = []

    def fake_download_json(uri: str):
        if "sk/runners/sk_gcc_release/runner_latest_meta.json" in uri:
            return ({"project": "sk", "preset": "sk_gcc_release", "source_ref": head_sha}, None)
        return (None, "404")

    monkeypatch.setattr(gcs, "download_json", fake_download_json)
    monkeypatch.setattr(gcs, "write_object", lambda u, _: written.append(u))

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "skip_in_gcs"
    assert any("sk.json" in u for u in written)


def test_sk_skip_in_gcs_via_local_repo_meta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Local plugins/projects/sk/runner_latest_meta.json serves as a last-resort recognition of a configured runner."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    local_meta = tmp_path / "plugins" / "projects" / "sk" / "runner_latest_meta.json"
    local_meta.write_text(
        '{"bucket_path": "sk/runners/sk_gcc_release/kardome_runner", "source_ref": null}',
        encoding="utf-8",
    )
    out = _setup_env(monkeypatch, tmp_path)

    written: list[str] = []
    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "404"))
    monkeypatch.setattr(gcs, "object_exists", lambda _uri: False)
    monkeypatch.setattr(gcs, "write_object", lambda u, _: written.append(u))

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "skip_in_gcs"
    assert any("_workflow/uploaded/99999/sk.json" in u for u in written)


def test_meta_sha_match_still_classified_skip_in_gcs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """meta.source_ref matching HEAD_SHA → skip_in_gcs (regression guard for previous fast-path)."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
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
    row = _sk_publish_row(outputs)
    assert row["upload_action"] == "skip_in_gcs"
    assert any("sk.json" in u for u in written)


def test_mixed_matrix_splits_supported_and_no_bmt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A mixed matrix yields one sk row in matrix_publish and two rows in matrix_no_bmt."""
    monkeypatch.chdir(tmp_path)
    _ensure_local_project_layout(tmp_path, "sk")
    # hmtc + woven remain unsupported (no plugins/projects/<p>/project.json in tmp_path).
    out = _setup_env(monkeypatch, tmp_path, runner_matrix=_RUNNER_MATRIX_MIXED)

    monkeypatch.setattr(gcs, "download_json", lambda _uri: (None, "404"))
    monkeypatch.setattr(gcs, "object_exists", lambda _uri: False)
    monkeypatch.setattr(gcs, "write_object", lambda _u, _b: None)

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    publish = json.loads(outputs["matrix_publish"])
    no_bmt = json.loads(outputs["matrix_no_bmt"])

    publish_projects = sorted(e["project"] for e in publish["include"])
    no_bmt_projects = sorted(e["project"] for e in no_bmt["include"])

    assert publish_projects == ["sk"]
    assert no_bmt_projects == ["hmtc", "woven"]
    for row in no_bmt["include"]:
        assert row["bmt_supported"] == "false"
        assert row["upload_action"] == "no_bmt"


def test_skip_publish_runners_emits_empty_matrices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BMT_SKIP_PUBLISH_RUNNERS=1 short-circuits to empty matrices including matrix_no_bmt."""
    monkeypatch.chdir(tmp_path)
    out = _setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BMT_SKIP_PUBLISH_RUNNERS", "1")

    RunnerManager.from_env().filter_upload_matrix()

    outputs = _read_output(out)
    assert outputs["matrix_publish_keys"] == "[]"
    assert outputs["matrix_need_upload_keys"] == "[]"
    # matrix_no_bmt is present and empty as a shape guarantee.
    assert json.loads(outputs["matrix_no_bmt"])["include"] == []
