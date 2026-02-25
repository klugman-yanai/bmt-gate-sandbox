"""Tests for pending-trigger guard in run_trigger command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ci.commands import run_trigger


def _set_required_env(monkeypatch: pytest.MonkeyPatch, output_file: Path) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_RUN_ID", "10001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("BMT_STATUS_CONTEXT", "BMT Gate")
    monkeypatch.setenv("BMT_DESCRIPTION_PENDING", "pending")
    monkeypatch.setenv("BMT_DESCRIPTION_SUCCESS", "success")
    monkeypatch.setenv("BMT_DESCRIPTION_FAILURE", "failure")


def test_trigger_rejects_when_other_pending_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    _set_required_env(monkeypatch, output_file)
    runner = CliRunner()

    runtime_root = "gs://bucket-a/team/runtime"
    monkeypatch.setattr(
        run_trigger.gcloud_cli,
        "run_capture",
        lambda cmd: (
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
    monkeypatch.setattr(run_trigger.gcloud_cli, "upload_json", lambda uri, payload: uploaded.append(uri))

    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": "false_reject_namuh"}]})
    result = runner.invoke(
        run_trigger.command,
        [
            "--config-root",
            "remote",
            "--bucket",
            "bucket-a",
            "--bucket-prefix",
            "team",
            "--matrix-json",
            matrix,
            "--run-context",
            "dev",
        ],
    )
    assert result.exit_code != 0
    assert "pending run trigger" in str(result.exception).lower()
    assert uploaded == []


def test_trigger_allows_when_only_current_run_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    _set_required_env(monkeypatch, output_file)
    runner = CliRunner()

    current_trigger = "gs://bucket-a/team/runtime/triggers/runs/10001.json"
    monkeypatch.setattr(run_trigger.gcloud_cli, "run_capture", lambda cmd: (0, f"{current_trigger}\n"))
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(run_trigger.gcloud_cli, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))

    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": "false_reject_namuh"}]})
    result = runner.invoke(
        run_trigger.command,
        [
            "--config-root",
            "remote",
            "--bucket",
            "bucket-a",
            "--bucket-prefix",
            "team",
            "--matrix-json",
            matrix,
            "--run-context",
            "dev",
        ],
    )
    assert result.exit_code == 0
    assert len(uploaded) == 1
    assert uploaded[0][0] == current_trigger
    assert output_file.exists()
