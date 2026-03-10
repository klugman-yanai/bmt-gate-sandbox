"""Tests for pending-trigger guard in trigger command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli.commands import trigger as run_trigger


def _set_required_env(monkeypatch: pytest.MonkeyPatch, output_file: Path, matrix: str, run_context: str) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GITHUB_RUN_ID", "10001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("BMT_STATUS_CONTEXT", "BMT Gate")
    monkeypatch.setenv("BMT_RUNTIME_CONTEXT", "BMT Runtime")
    monkeypatch.setenv("FILTERED_MATRIX_JSON", matrix)
    monkeypatch.setenv("RUN_CONTEXT", run_context)


def test_trigger_rejects_when_other_pending_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": "false_reject_namuh"}]})
    _set_required_env(monkeypatch, output_file, matrix, "dev")

    runtime_root = "gs://bucket-a/runtime"
    monkeypatch.setattr(
        run_trigger.gcloud,
        "run_capture",
        lambda _cmd: (
            0,
            "\n".join(
                [
                    f"{runtime_root}/triggers/runs/99999.json",
                    f"{runtime_root}/triggers/runs/10001.json",
                ]
            ),
        ),
    )
    uploaded: list[str] = []
    monkeypatch.setattr(run_trigger.gcloud, "upload_json", lambda uri, _payload: uploaded.append(uri))

    with pytest.raises(RuntimeError, match="pending run trigger"):
        run_trigger.run_trigger()
    assert uploaded == []


def test_trigger_allows_when_only_current_run_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": "false_reject_namuh"}]})
    _set_required_env(monkeypatch, output_file, matrix, "dev")

    current_trigger = "gs://bucket-a/runtime/triggers/runs/10001.json"
    monkeypatch.setattr(run_trigger.gcloud, "run_capture", lambda _cmd: (0, f"{current_trigger}\n"))
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(run_trigger.gcloud, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))

    run_trigger.run_trigger()
    assert len(uploaded) == 1
    assert uploaded[0][0] == current_trigger
    payload = uploaded[0][1]
    assert payload["description_pending"] == run_trigger.DEFAULT_DESCRIPTION_PENDING
    assert payload["runtime_status_context"] == "BMT Runtime"
    assert payload["legs"] == [
        {
            "project": "sk",
            "bmt_id": run_trigger.PROJECT_WIDE_BMT_ID,
            "run_id": payload["legs"][0]["run_id"],
            "request_scope": "project_wide",
            "triggered_at": payload["legs"][0]["triggered_at"],
        }
    ]
    assert "description_success" not in payload
    assert "description_failure" not in payload
    assert "code_manifest_digest" not in payload
    assert output_file.exists()


def test_trigger_collapses_multiple_rows_to_unique_project_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps(
        {
            "include": [
                {"project": "sk", "bmt_id": "foo"},
                {"project": "sk", "bmt_id": "bar"},
                {"project": "lgtv", "bmt_id": "baz"},
            ]
        }
    )
    _set_required_env(monkeypatch, output_file, matrix, "dev")

    current_trigger = "gs://bucket-a/runtime/triggers/runs/10001.json"
    monkeypatch.setattr(run_trigger.gcloud, "run_capture", lambda _cmd: (0, f"{current_trigger}\n"))
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(run_trigger.gcloud, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))

    run_trigger.run_trigger()
    payload = uploaded[0][1]
    legs = payload["legs"]
    assert isinstance(legs, list)
    assert len(legs) == 2
    assert [row["project"] for row in legs] == ["sk", "lgtv"]
    assert all(row["bmt_id"] == run_trigger.PROJECT_WIDE_BMT_ID for row in legs)
    assert all(row["request_scope"] == "project_wide" for row in legs)


def test_trigger_rejects_queueing_for_pr_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": "false_reject_namuh"}]})
    _set_required_env(monkeypatch, output_file, matrix, "pr")
    monkeypatch.setenv("PR_NUMBER", "42")

    runtime_root = "gs://bucket-a/runtime"
    monkeypatch.setattr(
        run_trigger.gcloud,
        "run_capture",
        lambda _cmd: (
            0,
            "\n".join(
                [
                    f"{runtime_root}/triggers/runs/99999.json",
                    f"{runtime_root}/triggers/runs/10001.json",
                ]
            ),
        ),
    )
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(run_trigger.gcloud, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))
    with pytest.raises(RuntimeError, match="pending run trigger"):
        run_trigger.run_trigger()
    assert uploaded == []
