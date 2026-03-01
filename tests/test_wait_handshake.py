"""Tests for .github/scripts/ci/commands/wait_handshake.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ci.commands import wait_handshake


def test_wait_handshake_success_uses_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}/runtime"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"
    runtime_status_uri = f"{runtime_root}/triggers/status/{run_id}.json"

    def fake_exists(uri: str) -> bool:
        return uri == trigger_uri

    monkeypatch.setattr(wait_handshake.gcloud_cli, "gcs_exists", fake_exists)
    monkeypatch.setattr(
        wait_handshake.gcloud_cli,
        "download_json",
        lambda _uri: (
            {
                "requested_leg_count": 2,
                "accepted_leg_count": 2,
                "accepted_legs": [{"project": "sk", "bmt_id": "false_reject_namuh"}],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        wait_handshake.gcloud_cli,
        "vm_describe",
        lambda *_args, **_kwargs: {"status": "RUNNING"},
    )

    result = runner.invoke(
        wait_handshake.command,
        [
            "--bucket",
            bucket,
            "--workflow-run-id",
            run_id,
            "--timeout-sec",
            "5",
            "--poll-interval-sec",
            "1",
            "--github-output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert f"Expected runtime status path: {runtime_status_uri}" in result.output
    content = output_file.read_text(encoding="utf-8")
    assert f"handshake_uri={runtime_root}/triggers/acks/{run_id}.json" in content


def test_wait_handshake_fails_fast_on_status_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When ack is never written, command times out with RuntimeError (fixed runtime path)."""
    runner = CliRunner()
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}/runtime"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"
    runtime_status_uri = f"{runtime_root}/triggers/status/{run_id}.json"

    def fake_exists(uri: str) -> bool:
        if uri == trigger_uri:
            return True
        return uri == f"gs://{bucket}/triggers/status/{run_id}.json" and uri != runtime_status_uri

    monkeypatch.setattr(wait_handshake.gcloud_cli, "gcs_exists", fake_exists)
    monkeypatch.setattr(wait_handshake.gcloud_cli, "download_json", lambda _uri: (None, None))

    result = runner.invoke(
        wait_handshake.command,
        [
            "--bucket",
            bucket,
            "--workflow-run-id",
            run_id,
            "--timeout-sec",
            "2",
            "--poll-interval-sec",
            "1",
            "--github-output",
            str(output_file),
        ],
    )

    assert result.exit_code != 0
    assert result.exception is not None
    err = str(result.exception)
    assert "Timed out waiting for VM handshake ack" in err
    assert runtime_root in err or "runtime" in err
