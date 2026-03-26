"""Tests for .github/bmt/ci/handshake.py HandshakeManager.wait()."""

from __future__ import annotations

from pathlib import Path

import pytest
from bmt_gate import gcs as gcs_module
from bmt_gate import vm as vm_module
from bmt_gate.handshake import HandshakeManager

from tools.repo.sk_bmt_ids import SK_BMT_FALSE_REJECT_NAMUH


@pytest.fixture(autouse=True)
def _required_bmt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")


def test_wait_handshake_success_uses_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"
    ack_uri = f"{runtime_root}/triggers/acks/{run_id}.json"

    monkeypatch.setenv("GCS_BUCKET", bucket)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("BMT_HANDSHAKE_TIMEOUT_SEC", "5")

    def fake_exists(uri: str) -> bool:
        return uri == trigger_uri

    monkeypatch.setattr(gcs_module, "object_exists", fake_exists)
    monkeypatch.setattr(
        gcs_module,
        "download_json",
        lambda _uri: (
            {
                "requested_leg_count": 2,
                "accepted_leg_count": 2,
                "accepted_legs": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH}],
            },
            None,
        ),
    )
    monkeypatch.setattr(vm_module, "vm_describe", lambda *_args, **_kwargs: {"status": "RUNNING"})

    HandshakeManager.from_env().wait(timeout_sec=5)

    captured = capsys.readouterr()
    assert "Waiting for VM handshake ack" in captured.out
    assert "VM handshake received" in captured.out
    content = output_file.read_text(encoding="utf-8")
    assert f"handshake_uri={ack_uri}" in content
    assert "handshake_support_resolution_version=v1" in content
    assert "handshake_run_disposition=accepted" in content
    assert "handshake_requested_legs=" in content
    assert "handshake_rejected_legs=" in content


def test_wait_handshake_fails_fast_on_status_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When ack is never written, command times out with RuntimeError (fixed runtime path)."""
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"

    monkeypatch.setenv("GCS_BUCKET", bucket)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("BMT_HANDSHAKE_TIMEOUT_SEC", "2")

    def fake_exists(uri: str) -> bool:
        return uri == trigger_uri

    monkeypatch.setattr(gcs_module, "object_exists", fake_exists)
    monkeypatch.setattr(gcs_module, "download_json", lambda _uri: (None, None))
    monkeypatch.setattr(vm_module, "vm_describe", lambda *_args, **_kwargs: {"status": "RUNNING"})

    with pytest.raises(RuntimeError, match="Timed out waiting for VM handshake"):
        HandshakeManager.from_env().wait(timeout_sec=2)


def test_wait_handshake_preserves_v2_support_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "github_output.txt"

    bucket = "bucket-a"
    run_id = "123456"
    runtime_root = f"gs://{bucket}"
    trigger_uri = f"{runtime_root}/triggers/runs/{run_id}.json"

    monkeypatch.setenv("GCS_BUCKET", bucket)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("BMT_HANDSHAKE_TIMEOUT_SEC", "5")

    monkeypatch.setattr(gcs_module, "object_exists", lambda uri: uri == trigger_uri)
    monkeypatch.setattr(
        gcs_module,
        "download_json",
        lambda _uri: (
            {
                "support_resolution_version": "v2",
                "run_disposition": "accepted_but_empty",
                "requested_leg_count": 2,
                "accepted_leg_count": 0,
                "requested_legs": [
                    {
                        "index": 0,
                        "project": "foo",
                        "bmt_id": "foo_release",
                        "run_id": "r1",
                        "decision": "rejected",
                        "reason": "manager_missing",
                    }
                ],
                "accepted_legs": [],
                "rejected_legs": [
                    {
                        "index": 0,
                        "project": "foo",
                        "bmt_id": "foo_release",
                        "run_id": "r1",
                        "reason": "manager_missing",
                    }
                ],
            },
            None,
        ),
    )
    monkeypatch.setattr(vm_module, "vm_describe", lambda *_args, **_kwargs: {"status": "RUNNING"})

    HandshakeManager.from_env().wait(timeout_sec=5)

    content = output_file.read_text(encoding="utf-8")
    assert "handshake_support_resolution_version=v2" in content
    assert "handshake_run_disposition=accepted_but_empty" in content
    assert '"decision":"rejected"' in content
    assert '"reason":"manager_missing"' in content
