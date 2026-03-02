"""Tests for .github/bmt/commands/wait_handshake.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmt.commands import vm as wait_handshake


def test_wait_handshake_success_uses_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}/runtime"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"
    runtime_status_uri = f"{runtime_root}/triggers/status/{run_id}.json"

    monkeypatch.setenv("GCS_BUCKET", bucket)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("BMT_HANDSHAKE_TIMEOUT_SEC", "5")

    def fake_exists(uri: str) -> bool:
        return uri == trigger_uri

    monkeypatch.setattr(wait_handshake.gcloud, "gcs_exists", fake_exists)
    monkeypatch.setattr(
        wait_handshake.gcloud,
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
        wait_handshake.gcloud,
        "vm_describe",
        lambda *_args, **_kwargs: {"status": "RUNNING"},
    )

    wait_handshake.run_wait_handshake()

    captured = capsys.readouterr()
    assert f"Expected runtime status path: {runtime_status_uri}" in captured.out
    content = output_file.read_text(encoding="utf-8")
    assert f"handshake_uri={runtime_root}/triggers/acks/{run_id}.json" in content


def test_wait_handshake_fails_fast_on_status_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When ack is never written, command times out with RuntimeError (fixed runtime path)."""
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}/runtime"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"

    monkeypatch.setenv("GCS_BUCKET", bucket)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("BMT_HANDSHAKE_TIMEOUT_SEC", "2")

    def fake_exists(uri: str) -> bool:
        return uri == trigger_uri

    monkeypatch.setattr(wait_handshake.gcloud, "gcs_exists", fake_exists)
    monkeypatch.setattr(wait_handshake.gcloud, "download_json", lambda _uri: (None, None))

    with pytest.raises(RuntimeError, match="Timed out waiting for VM handshake ack"):
        wait_handshake.run_wait_handshake()
